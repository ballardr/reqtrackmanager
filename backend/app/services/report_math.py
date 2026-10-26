"""
Module: services.report_math

Mathematics in reports: which TeX is accepted, where it is found in text, and how it is drawn for each output.

Responsibilities:
- `tex_problem`: the command allow-list. TeX is untrusted input (a record field, a layout author), so only
  commands, environments and characters named here ever reach a converter.
- `split_math`: find `\\( ... \\)` (inline) and `$$ ... $$` (display) in text, honouring a per-character mask of
  where a delimiter counts (authored text and math-capable record fields, never other record values).
- `typeset`: TeX to a sanitised SVG with its size and baseline offset (PDF, HTML, and the picture Word falls back to).
- `omml`: TeX to Word's native equation markup for the subset pinned by the golden test, else `None`.
- `source_of`: an equation written out as the author typed it, which is what every output shows when it cannot
  draw one.

Design decisions:
- **Allow-list, not block-list.** `latex2mathml` is lenient (`\\href{http://x}{y}` became a link, `\\input` passed
  through as text), so the check runs before any conversion and names what is allowed. The text of `\\text{}` is
  limited to plain characters, so markup in a record cannot ride inside it.
- **A bare `$` is never a delimiter**, so prices and shell snippets in record text are left alone; `\\(` and `$$`
  are the only openers, and an opener with no closer is ordinary text.
- **SVG is the one drawn form.** `ziamath` draws glyphs as paths (no font, no `<text>`), in plain SVG 1 mode
  because `svglib` garbles its SVG 2 `symbol`/`use` output. Its output still goes through
  `report_svg.sanitize_svg`, like every figure.
- **Word gets native equations only for a tested subset.** `mathml2omml` output is unwrapped from its empty
  `m:box` wrappers, a square root gets the `m:deg` Word requires, and anything using an element outside
  `OMML_ELEMENTS` (accents, limits written under an operator, aligned equations) or a limit operator such as
  `\\lim` is refused so the caller draws the picture instead. The subset was checked in LibreOffice (decisions log,
  "PDF engine, math, ODF and tree bake-off") and opened in Word by a person.
- **Failure degrades to source, never to an error**: a TeX parse failure, an unsupported construct or a converter
  exception returns `None` and the renderer prints the author's own text.
- `ziamath` keeps module-level font state, so typesetting is serialised by a lock; results are cached because a
  layout repeats the same equation once per record.

Dependencies: `ziamath` (MIT, with the STIX Two Math font under the SIL OFL), `latex2mathml` and `mathml2omml`
(MIT), `lxml`; `services.report_svg` (SVG sanitiser and rasteriser).
"""

from __future__ import annotations

import re
import threading
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache

import latex2mathml.converter
import mathml2omml
import ziamath
from lxml import etree

from app.services.report_svg import sanitize_svg, svg_png

#: Longest TeX source accepted for one equation, in characters.
MAX_TEX_CHARS = 2000
#: Deepest `{ }` nesting accepted.
MAX_TEX_DEPTH = 10
#: Type size, in points, equations are drawn at: the body text size inline, a little larger as a display.
INLINE_SIZE_PT = 10.0
DISPLAY_SIZE_PT = 12.0

OMML_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"

_GREEK = (
    "alpha beta gamma delta epsilon varepsilon zeta eta theta vartheta iota kappa lambda mu nu xi pi varpi rho varrho "
    "sigma varsigma tau upsilon phi varphi chi psi omega Gamma Delta Theta Lambda Xi Pi Sigma Upsilon Phi Psi Omega"
)
_FUNCTIONS = (
    "sin cos tan cot sec csc arcsin arccos arctan sinh cosh tanh log ln exp lim limsup liminf max min sup inf det dim "
    "gcd arg deg ker Pr"
)
_OPERATORS = "sum prod int iint iiint oint bigcup bigcap"
_RELATIONS = (
    "leq le geq ge neq ne approx equiv sim simeq cong propto ll gg in notin ni subset supset subseteq supseteq perp "
    "parallel mid"
)
_BINARY = "pm mp times div cdot ast star circ bullet oplus ominus otimes cup cap setminus wedge vee land lor neg lnot"
_ARROWS = "to rightarrow leftarrow leftrightarrow Rightarrow Leftarrow Leftrightarrow mapsto implies iff uparrow downarrow"
_SYMBOLS = (
    "infty partial nabla forall exists nexists emptyset varnothing angle prime ldots cdots vdots ddots hbar ell Re Im "
    "aleph triangle"
)
_DELIMITERS = "langle rangle lfloor rfloor lceil rceil lvert rvert vert Vert"
_SIZES = "left right big Big bigg Bigg bigl bigr Bigl Bigr biggl biggr Biggl Biggr"
_STRUCTURE = (
    "frac dfrac tfrac sqrt binom overline underline hat bar vec dot ddot tilde widehat widetilde overrightarrow "
    "overbrace underbrace stackrel mathrm mathbf mathit mathbb mathcal mathsf mathtt boldsymbol quad qquad not"
)
#: Commands that take one `{...}` of plain text.
TEXT_COMMANDS = frozenset({"text", "textbf", "textit", "operatorname"})

ALLOWED_COMMANDS = frozenset(
    " ".join((
        _GREEK, _FUNCTIONS, _OPERATORS, _RELATIONS, _BINARY, _ARROWS, _SYMBOLS, _DELIMITERS, _SIZES, _STRUCTURE,
        "begin end text textbf textit operatorname",
    )).split()
)
#: Commands written as a backslash and one character (`\\,` `\\{` ...).
ALLOWED_SYMBOL_COMMANDS = frozenset(",;: !{}|_%#&$\\")
ALLOWED_ENVIRONMENTS = frozenset({"matrix", "pmatrix", "bmatrix", "vmatrix", "Vmatrix", "cases", "array", "aligned"})
#: What the text of `\\text{...}` may hold: no braces, backslashes, markup or TeX specials.
PLAIN_TEXT = re.compile(r"[A-Za-z0-9 .,;:!?()'+\-=/*\[\]]*")
FORBIDDEN_CHARACTERS = frozenset('%#$~"`')
_ASCII_LETTER = re.compile(r"[A-Za-z]")
_ENVIRONMENT = re.compile(r"\{([A-Za-z]+)\}")

#: Word equation elements the golden test covers. Anything else sends the caller to the picture.
OMML_ELEMENTS = frozenset({
    "oMath", "r", "rPr", "sty", "nor", "t", "f", "num", "den", "sSup", "sSub", "sSubSup", "e", "sub", "sup", "rad",
    "radPr", "degHide", "deg", "nary", "naryPr", "chr", "limLoc", "d", "dPr", "begChr", "endChr", "m", "mr",
})

#: Limit operators: Word's equation editor stacks their subscript underneath, which the converter's output does not,
#: so an equation using one is drawn as a picture instead.
_PICTURE_ONLY = re.compile(r"\\(?:lim|limsup|liminf)(?![A-Za-z])")
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

_typeset_lock = threading.Lock()
ziamath.config.svg2 = False


@dataclass(frozen=True)
class MathSegment:
    """One piece of a text: ordinary `text`, an `inline` equation or a `display` equation (`value` is the TeX)."""

    kind: str
    value: str


@dataclass(frozen=True)
class TypesetEquation:
    """An equation drawn as SVG.

    Attributes:
        svg: Sanitised SVG whose user units are points at the size it was typeset at.
        width: Width in points.
        height: Height in points.
        descent: How far the drawing extends below the text baseline, in points (zero when none).
    """

    svg: str
    width: float
    height: float
    descent: float


def normalise_tex(tex: str) -> str:
    """The TeX with every run of whitespace (including newlines) as one space and the ends trimmed."""
    return " ".join(tex.split())


def tex_problem(tex: str) -> str | None:
    """Why `tex` may not be typeset, or `None` when it passes the allow-list.

    Checks length, characters, every `\\command` against `ALLOWED_COMMANDS`, environments (matching
    `\\begin`/`\\end`), the plain-text arguments, `{ }` balance and depth, and that `&` appears only inside an
    environment. It does not prove the TeX is well formed; a converter failure is handled by `typeset`.

    Args:
        tex: TeX source, without delimiters.

    Returns:
        A sentence for the author, or `None`.
    """
    if not tex.strip():
        return "The equation is empty."
    if len(tex) > MAX_TEX_CHARS:
        return f"An equation is limited to {MAX_TEX_CHARS} characters."
    environments: list[str] = []
    depth, i, n = 0, 0, len(tex)
    while i < n:
        ch = tex[i]
        if ch in FORBIDDEN_CHARACTERS:
            return f"The character {ch} is not supported in equations."
        if not ch.isspace() and unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Co", "Cn"):
            return "An equation may not contain control or invisible characters."
        if ch == "{":
            depth += 1
            if depth > MAX_TEX_DEPTH:
                return f"Braces are nested more than {MAX_TEX_DEPTH} deep."
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return "A } has no matching {."
        elif ch == "&" and not environments:
            return "An & is only used inside a matrix, cases or aligned environment."
        elif ch == "\\":
            i, problem = _command(tex, i, environments)
            if problem:
                return problem
            continue
        i += 1
    if depth:
        return "A { is never closed."
    if environments:
        return f"\\begin{{{environments[-1]}}} is never closed."
    return None


def _command(tex: str, start: int, environments: list[str]) -> tuple[int, str | None]:
    """Checks the command at `tex[start]` (a backslash); returns the index after it and any problem."""
    n = len(tex)
    j = start + 1
    if j >= n:
        return n, "A backslash must be followed by a command."
    if not _ASCII_LETTER.match(tex[j]):
        if tex[j] in ALLOWED_SYMBOL_COMMANDS:
            return j + 1, None
        return j + 1, f"The command \\{tex[j]} is not supported in equations."
    k = j
    while k < n and _ASCII_LETTER.match(tex[k]):
        k += 1
    name = tex[j:k]
    if name not in ALLOWED_COMMANDS:
        return k, f"The command \\{name[:30]} is not supported in equations."
    if name in ("begin", "end"):
        found = _ENVIRONMENT.match(tex, k)
        if not found or found.group(1) not in ALLOWED_ENVIRONMENTS:
            return k, f"\\{name} must name one of: {', '.join(sorted(ALLOWED_ENVIRONMENTS))}."
        if name == "begin":
            environments.append(found.group(1))
        elif not environments or environments.pop() != found.group(1):
            return found.end(), f"\\end{{{found.group(1)}}} does not match an open \\begin."
        return found.end(), None
    if name in TEXT_COMMANDS:
        m = k
        while m < n and tex[m].isspace():
            m += 1
        close = tex.find("}", m) if m < n and tex[m] == "{" else -1
        if close < 0 or not PLAIN_TEXT.fullmatch(tex, m + 1, close):
            return k, f"\\{name} takes plain text in braces (letters, digits, spaces and basic punctuation)."
        return close + 1, None
    return k, None


def source_of(tex: str, *, display: bool) -> str:
    """The equation as the author typed it, with its delimiters: what an output shows when it cannot draw it."""
    return f"$${tex}$$" if display else f"\\({tex}\\)"


_OPENERS = re.compile(r"\\\(|\$\$")
_CLOSER = {"\\(": "\\)", "$$": "$$"}


def split_math(text: str, eligible: Sequence[bool] | None = None) -> list[MathSegment]:
    """Splits `text` into ordinary text and equations.

    `\\( x \\)` is inline and `$$ x $$` is display. An opener with no closer, or enclosing nothing, stays text, so
    stray delimiters never raise.

    Args:
        text: The text.
        eligible: One flag per character of `text`; a delimiter only counts where both its characters are
            eligible (so a delimiter inside a record value that is not math-capable stays text). `None` means
            every character counts.

    Returns:
        Segments in order; adjacent text is joined. The equations' TeX is not checked here.
    """
    if eligible is not None and len(eligible) != len(text):
        raise ValueError("eligible must have one flag per character")

    def counts(position: int, delimiter: str) -> bool:
        return eligible is None or all(eligible[position:position + len(delimiter)])

    segments: list[MathSegment] = []
    plain: list[str] = []
    cursor = 0
    for opener in _OPENERS.finditer(text):
        if opener.start() < cursor or not counts(opener.start(), opener.group()):
            continue
        closer = _CLOSER[opener.group()]
        end = text.find(closer, opener.end())
        while end >= 0 and not counts(end, closer):
            end = text.find(closer, end + 1)
        if end < 0 or not text[opener.end():end].strip():
            continue
        plain.append(text[cursor:opener.start()])
        if "".join(plain):
            segments.append(MathSegment("text", "".join(plain)))
        plain = []
        segments.append(MathSegment("display" if opener.group() == "$$" else "inline", text[opener.end():end]))
        cursor = end + len(closer)
    plain.append(text[cursor:])
    if "".join(plain):
        segments.append(MathSegment("text", "".join(plain)))
    return segments


_ROOT_SVG = re.compile(r"<svg\b[^>]*>")
_VIEW_BOX = re.compile(r'viewBox="\s*(-?[\d.]+)[ ,]+(-?[\d.]+)[ ,]+([\d.]+)[ ,]+([\d.]+)\s*"')


def typeset(tex: str, display: bool = False) -> TypesetEquation | None:
    """Draws `tex` as SVG.

    Args:
        tex: TeX source (whitespace is normalised).
        display: `True` for a display equation (larger, display-style operators), `False` for inline.

    Returns:
        The drawing, or `None` when the TeX fails the allow-list, cannot be parsed or cannot be drawn.
    """
    return _typeset(normalise_tex(tex), display)


@lru_cache(maxsize=2048)
def _typeset(source: str, display: bool) -> TypesetEquation | None:
    """`typeset` for TeX already normalised, cached on it."""
    if tex_problem(source):
        return None
    size = DISPLAY_SIZE_PT if display else INLINE_SIZE_PT
    try:
        with _typeset_lock:
            drawn = ziamath.Latex(source, size=size, inline=not display).svg()
        clean = sanitize_svg(drawn)
        root = _ROOT_SVG.search(clean)
        box = _VIEW_BOX.search(root.group()) if root else None
        if box is None:
            return None
        top, width, height = float(box.group(2)), float(box.group(3)), float(box.group(4))
    except Exception:  # noqa: BLE001 - ziamath raises assertion, parse and token errors on malformed TeX; it degrades to source
        return None
    if width <= 0 or height <= 0:
        return None
    return TypesetEquation(clean, width, height, max(0.0, top + height))


def png_of(equation: TypesetEquation, *, zoom: float = 4.0) -> bytes | None:
    """A transparent PNG of a drawn equation at `zoom` pixels per point, or `None` if it cannot be rasterised."""
    try:
        return svg_png(equation.svg, zoom=zoom, background=None)
    except Exception:  # noqa: BLE001 - a figure that cannot be drawn must never break report generation
        return None


def scaled_svg(equation: TypesetEquation, unit_per_point: float, unit: str) -> str:
    """The SVG with its root `width` and `height` expressed in `unit` (`em` for HTML), keeping the aspect ratio.

    Args:
        equation: The drawing.
        unit_per_point: How many `unit`s one point is worth.
        unit: A CSS length unit, letters only.
    """
    width = f'width="{equation.width * unit_per_point:.3f}{unit}"'
    height = f'height="{equation.height * unit_per_point:.3f}{unit}"'
    root = _ROOT_SVG.search(equation.svg)
    if root is None:
        return equation.svg
    tag = re.sub(r'\bwidth="[^"]*"', width, root.group(), count=1)
    tag = re.sub(r'\bheight="[^"]*"', height, tag, count=1)
    return equation.svg[:root.start()] + tag + equation.svg[root.end():]


def _unbox(root: etree._Element) -> None:
    """Replaces each `m:box` by what it holds: the converter wraps every group in an empty box Word does not need."""
    box_tag, e_tag = f"{{{OMML_NS}}}box", f"{{{OMML_NS}}}e"
    for box in list(root.iter(box_tag)):
        parent = box.getparent()
        if parent is None:
            continue
        holder = box.find(e_tag)
        index = parent.index(box)
        for offset, child in enumerate(list(holder) if holder is not None else []):
            parent.insert(index + offset, child)
        parent.remove(box)


def _give_roots_a_degree(root: etree._Element) -> None:
    """Adds the hidden degree Word requires to a square root (`mathml2omml` leaves it out)."""
    for rad in root.iter(f"{{{OMML_NS}}}rad"):
        if rad.find(f"{{{OMML_NS}}}deg") is None:
            properties = etree.Element(f"{{{OMML_NS}}}radPr")
            etree.SubElement(properties, f"{{{OMML_NS}}}degHide").set(f"{{{OMML_NS}}}val", "1")
            rad.insert(0, properties)
            rad.insert(1, etree.Element(f"{{{OMML_NS}}}deg"))


def omml(tex: str) -> str | None:
    """Word's native markup (`<m:oMath>`) for `tex`, or `None` when it is outside the supported subset.

    Args:
        tex: TeX source (whitespace is normalised).

    Returns:
        One `m:oMath` element as a string declaring the `m` namespace, ready to parse and append to a
        paragraph; `None` when the TeX fails the allow-list, a converter fails, the result is not well formed
        or it uses an element outside `OMML_ELEMENTS` (the caller then draws the picture).
    """
    return _omml(normalise_tex(tex))


@lru_cache(maxsize=2048)
def _omml(source: str) -> str | None:
    """`omml` for TeX already normalised, cached on it."""
    if tex_problem(source) or _PICTURE_ONLY.search(source):
        return None
    try:
        converted = mathml2omml.convert(latex2mathml.converter.convert(source))
        root = etree.fromstring(
            f'<w xmlns:m="{OMML_NS}">{converted}</w>'.encode(),
            etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False),
        )
    except Exception:  # noqa: BLE001 - both converters raise assorted errors on TeX they cannot handle
        return None
    _unbox(root)
    _give_roots_a_degree(root)
    for run_text in root.iter(f"{{{OMML_NS}}}t"):
        run_text.set(_XML_SPACE, "preserve")  # keeps the space in `\text{if }`; Word trims it otherwise
    if any(etree.QName(element).localname not in OMML_ELEMENTS for element in root.iter() if element is not root):
        return None
    if len(root) != 1 or etree.QName(root[0]).localname != "oMath":
        return None
    return etree.tostring(root[0], encoding="unicode")


__all__ = [
    "ALLOWED_COMMANDS", "ALLOWED_ENVIRONMENTS", "DISPLAY_SIZE_PT", "INLINE_SIZE_PT", "MAX_TEX_CHARS", "OMML_ELEMENTS",
    "OMML_NS", "MathSegment", "TypesetEquation", "normalise_tex", "omml", "png_of", "scaled_svg", "source_of",
    "split_math", "tex_problem", "typeset",
]
