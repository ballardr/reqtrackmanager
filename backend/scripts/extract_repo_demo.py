"""
Module: scripts.extract_repo_demo

Builds the fixture behind the "ReqTrackManager (this product)" demo project
from this repository's own documents:

- `docs/requirements.md`: components, categories and requirements (with level and target version).
- `docs/decisions.md`: decisions, each with its statement, rationale and `Decided by` attribution.
- `docs/soc2/`: the Security and Confidentiality criteria as a compliance standard, the assessed status of
  each criterion, the policies as evidence and the open known gaps as risks.
- `docs/solution-architecture.md`: the core architecture principles as guiding principles.

Responsibilities:
- Parse the Markdown documents deterministically (no network, no clock, no randomness), so the fixture can be
  regenerated and compared with the committed file.
- Write `backend/scripts/data/repo_demo.json` (`--write`) or report drift (`--check`, exit status 1).

Design decisions:
- Reading the documents never modifies them; `docs/requirements.md` remains read-only for tooling.
- A decision is an entry that records a `Decided by` attribution, or an unattributed one in the log's original design
  sections; hand-reviewed title rewrites and exclusions live in `data/repo_demo_curation.json`. The log only
  grows, so `--check` treats a new entry as current and an edited or removed one as drift.
- Resolved known gaps (struck through in the policies) are not extracted; only open gaps become risks.

External dependencies: the Python standard library only.

Run from the repository root:
    python backend/scripts/extract_repo_demo.py --write
    python backend/scripts/extract_repo_demo.py --check
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = Path(__file__).resolve().parent / "data" / "repo_demo.json"

FIXTURE_VERSION = 1
DECISION_LIMIT = 1000
MIN_DECISION_BODY = 80
MAX_REQUIREMENT_NAME = 480
MAX_TITLE = 290

# A requirement's level and target version become tags, and the target versions become stages.
STATUS_BY_SYMBOL = {"✅": "compliant", "🟡": "in_progress", "🔴": "non_compliant"}

RISK_TYPE_BY_POLICY = {
    "data-retention-and-disposal-policy": "Compliance",
    "risk-assessment-policy": "Compliance",
    "security-awareness-training-policy": "Compliance",
    "system-operations-monitoring-and-logging-policy": "Operational",
    "change-management-and-secure-development-policy": "Operational",
}

# Ordered keyword rules assigning a decision type from its section heading and title.
DECISION_TYPE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Operational", ("deploy", "docker", "backup", "monitor", "metric", "observab", "health", "storage", "disaster",
                     "performance", "profil", "infrastructure", "restore", "scal")),
    ("Design", ("frontend", "ui ", "ux", "style", "layout", "page", "form", "navigation", "dialog", "designer",
                "widget", "dashboard", "label", "wording", "storybook", "modal", "tooltip")),
    ("Architecture", ("architect", "module", "registry", "boundary", "nesting", "hierarch", "schema", "database",
                      "migration", "data model", "bundle", "extension", "enum", "table")),
    ("Strategy", ("plan", "review", "roadmap", "requirements.md", "scope", "policy", "soc 2", "compliance", "process",
                  "phase")),
)
DEFAULT_DECISION_TYPE = "Engineering"

# The log's original design sections, whose unattributed bullets are all design choices.
FOUNDATIONAL_SECTIONS = frozenset({
    "Authentication and identity", "Roles and permissions", "Requirement lifecycle and change management",
    "Reporting", "Realtime", "Infrastructure", "Testing", "Pelion (v2)",
})
TITLE_BREAK_AT = 100
MIN_STATEMENT = 40
# Leads that mark a note, an endpoint, a file, a result or a status line, not a decision.
NOT_A_DECISION = re.compile(
    r"^(?:read |verified|finding \d|docs website|tests?\b|not (?:changed|built|covered|applicable|run|confirmed)|new files|"
    r"what exists|(?:get|post|put|patch|delete) /|[\w./-]+\.(?:py|md|tsx?|ya?ml)\b|.* needed no changes|\d+[a-z]? is done|"
    r"results?\b|result of|findings?\b|addendum|follow-up|spike\b|phase added|scope statement|order of work|"
    r"specification for|decided by|raised by|signed off|approved at|answers?\b|questions?\b|what (?:was|changed|it found|"
    r"travels|was asked)|left open|carried into|regression check|evidence standard|cause\b|audit method|"
    r"full-mix|worker-scaling|ten-project|six workers|one-worker|raspberry|memory high-water|[a-z]+ run\b|"
    r".*\b(?:found and fixed|found on the way|found while|found by the full run|defects? (?:found|fixed)|a defect|"
    r"bug found|gaps closed|pre-existing|flaky|ci failures|ci test step|race|stale|leaked|fixed in passing|"
    r"fixed on the way|fixed|deferred|compatibility alias)\b)",
    re.I,
)
# Generic leads that mean nothing without the section they sit under.
MAX_GENERIC_WORDS = 4
MAX_LABEL = 45
CURATION_PATH = Path(__file__).resolve().parent / "data" / "repo_demo_curation.json"


def load_curation() -> dict:
    """Reads the hand-reviewed title rewrites and exclusions for the decision log.

    Returns:
        A dictionary with `titles` (key to replacement title) and `exclude` (key to reason); empty when the file
        does not exist.
    """
    if not CURATION_PATH.exists():
        return {"titles": {}, "exclude": {}}
    data = json.loads(CURATION_PATH.read_text(encoding="utf-8"))
    return {"titles": data.get("titles", {}), "exclude": data.get("exclude", {})}


CURATION = load_curation()


def read(relative: str) -> str:
    """Returns the text of a repository file.

    Args:
        relative: Path relative to the repository root.

    Returns:
        The file contents.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def clean_cell(text: str) -> str:
    """Normalises a Markdown table cell: line breaks become newlines and surrounding space is removed.

    Args:
        text: The raw cell text.

    Returns:
        The cleaned text.
    """
    return re.sub(r"<br\s*/?>", "\n", text).strip()


def shorten(text: str, limit: int) -> str:
    """Cuts text at a word boundary below `limit` characters, adding an ellipsis when it was cut.

    Args:
        text: The text to shorten.
        limit: The maximum length of the result.

    Returns:
        The text unchanged when short enough, else the shortened text.
    """
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:.") + "…"


def extract_requirements() -> tuple[list[dict], list[dict], list[dict]]:
    """Parses `docs/requirements.md` into components, requirements and stages.

    A top-level heading that contains requirement tables is a component and each second-level heading under it is a
    category. Component and category prefixes are the two segments of the source identifier (`C-G-01` gives
    component `C`, category `G`), so a project code reads like the source identifier. The stages come from the
    version table in Appendix A.

    Returns:
        A tuple of (components with their categories, requirements, stages).
    """
    components: dict[str, dict] = {}
    requirements: list[dict] = []
    section = category = ""
    for line in read("docs/requirements.md").splitlines():
        if line.startswith("# "):
            section, category = line[2:].strip(), ""
        elif line.startswith("## "):
            category = line[3:].strip()
        match = re.match(r"\| ([A-Z]+-[A-Z]+-\d+) \| (.*) \| ([^|]+) \| ([^|]+) \|$", line)
        if not match or not category:
            continue
        code, body, level, target = match.group(1), clean_cell(match.group(2)), match.group(3).strip(), match.group(4).strip()
        component_prefix, category_prefix = code.split("-")[:2]
        component = components.setdefault(section, {"name": section, "prefix": component_prefix, "categories": {}})
        component["categories"].setdefault(category, {"name": category, "prefix": category_prefix})
        first, _, rest = body.partition("\n")
        labelled = {
            label: text.strip()
            for label, text in re.findall(r"\*\*([A-Za-z ]+):\*\*\s*(.*)", rest)
        }
        reasoning = labelled.pop("Reasoning", "")
        requirements.append({
            "source_id": code, "component": section, "category": category,
            "name": shorten(first, MAX_REQUIREMENT_NAME), "statement": first if len(first) > MAX_REQUIREMENT_NAME else "",
            "reasoning": reasoning, "description": "\n\n".join(f"**{label}:** {text}" for label, text in labelled.items()),
            "level": level, "target": target,
        })
    stages = [
        {"name": match.group(1), "summary": match.group(2)}
        for match in re.finditer(r"(?m)^\| ((?:Ossa|Pelion|Massif|Murchison) \(v\d\))\s*\| ([^|]+?)\s*\|$", read("docs/requirements.md"))
    ]
    return (
        [{**c, "categories": list(c["categories"].values())} for c in components.values()],
        requirements,
        stages,
    )


def decision_type(section: str, title: str) -> str:
    """Chooses a decision type name from a section heading and a decision title.

    Args:
        section: The second-level heading the decision sits under.
        title: The decision's title.

    Returns:
        One of the default decision type names.
    """
    haystack = f" {section} {title} ".lower()
    for type_name, keywords in DECISION_TYPE_RULES:
        if any(keyword in haystack for keyword in keywords):
            return type_name
    return DEFAULT_DECISION_TYPE


def clean_body(body: str) -> str:
    """Removes attribution notes and hard line breaks from a decision's text.

    Args:
        body: The text after the bold title, as written in the log.

    Returns:
        The text as running prose on one line.
    """
    body = re.sub(r"\(\*?Decided by:?\s*(?:User|Agent)[^)]*\)\.?", "", body)
    body = re.sub(r"\*{0,2}Decided by:?\s*(?:User|Agent)[^.*]*[.*]*", "", body)
    body = re.sub(r"\s+", " ", body)
    return body.strip(" .,:;—-") + ("." if body.strip().endswith(".") else "")


def split_statement(body: str) -> tuple[str, str]:
    """Splits a decision body into a one-sentence statement and the remaining rationale.

    Args:
        body: The decision text after its bold title.

    Returns:
        The statement (the first sentence, at most 400 characters) and the remaining text.
    """
    body = body.strip()
    match = re.search(r"(?<=[.!?])\s+(?=[A-Z`*(])", body)
    if match and match.start() <= 400:
        return body[: match.start()].strip(), body[match.end():].strip()
    if len(body) <= 400:
        return body, ""
    cut = body[:400].rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:") + "…", body[len(cut):].strip()


def entry_key(section: str, raw_title: str) -> str:
    """Returns the short stable key of a log entry, used by the curation file.

    Args:
        section: The second-level heading the entry sits under.
        raw_title: The entry's bold title as written.

    Returns:
        Six hexadecimal characters derived from the section and the title.
    """
    return hashlib.sha1(f"{section}|{raw_title}".encode()).hexdigest()[:6]


def clean_title(raw: str) -> str:
    """Turns a bold lead from the log into a readable decision title.

    Removes attribution notes, emphasis and code marks, review reference numbers (`N34`, `Q12`), and shortens a
    sentence-length lead at its first natural break.

    Args:
        raw: The bold text as written in the log.

    Returns:
        The cleaned title (possibly empty).
    """
    title = re.sub(r"\((?:[^()]*?)Decided by[^()]*\)", "", raw)
    title = re.sub(r"[\s—,;-]*Decided by.*$", "", title)
    title = title.replace("*", "").replace("`", "")
    title = re.sub(r"\((?:[NQRF]\d+[a-z]?[\s,/–-]*)+[^()]*\)", "", title)
    title = re.sub(r"\b[NQRF]\d+[a-z]?(?:[–-][NQRF]?\d+)?\b[:,]?\s*", "", title)
    title = re.sub(r"\s+", " ", title).strip(" .:,;—-(")
    title = re.sub(r"\s*\([^)]*$", "", title).strip(" .:,;—-")
    if len(title) > TITLE_BREAK_AT:
        for separator in (" — ", ": ", ", ", " (", " so ", " because ", " and "):
            head = title.split(separator, 1)[0]
            if 25 <= len(head) <= TITLE_BREAK_AT:
                title = head
                break
    return title[:1].upper() + title[1:]


def section_label(section: str) -> str:
    """Reduces a log section heading to the short subject it is about.

    Dates, numbered steps and module numbers are dropped, so a heading that numbers a module and a step and ends
    in a date reads as the module's name followed by the step's title.

    Args:
        section: The second-level heading.

    Returns:
        A short label, or an empty string when nothing readable remains.
    """
    label = re.sub(r"`", "", section)
    months = "January|February|March|April|May|June|July|August|September|October|November|December"
    label = re.sub(rf"\(\d{{4}}-\d\d-\d\d[^)]*\)|\((?:{months}) \d{{4}}\)", "", label)
    label = re.sub(r"Module \d+ \(([^)]+)\)", r"\1", label)
    tail = ""
    phase = re.search(r"[, ]*\bPhases? [\w.]+(?: to [\w.]+)?\s*(?:[:—-]\s*(.*))?$", label)
    if phase:
        tail = phase.group(1) or ""
        label = label[: phase.start()]
    label = re.sub(r"\s+", " ", label).strip(" ,:—-")
    tail = re.sub(r"\s+", " ", tail).strip(" ,:—-")
    if tail and len(tail) <= 40:
        label = f"{label}, {tail}" if label else tail
    for separator in (":", " — ", ","):
        if len(label) > MAX_LABEL:
            label = label.split(separator, 1)[0].strip()
    return label if 6 <= len(label) <= MAX_LABEL else ""


def contextual_title(title: str, section: str, repeated: bool) -> str:
    """Prefixes a title that cannot stand alone with its section's subject.

    Args:
        title: The cleaned title.
        section: The second-level heading the entry sits under.
        repeated: Whether the same title occurs on other entries.

    Returns:
        The title, as `Subject: title` when it is short or repeated.
    """
    label = section_label(section)
    if label and (len(title.split()) <= MAX_GENERIC_WORDS or repeated) and label.lower() not in title.lower():
        return f"{label}: {title}"
    return title


def is_decision_entry(title: str, statement: str) -> bool:
    """Tells whether a log bullet reads as a decision rather than a note, a route, a file or a status line.

    Args:
        title: The cleaned title.
        statement: The entry's first sentence.

    Returns:
        True when the entry is kept.
    """
    return (
        len(title.split()) >= 2 and len(statement) >= MIN_STATEMENT
        and not NOT_A_DECISION.match(title)
        and not re.fullmatch(r"[\w./{}\-_]+", title)
        and title[0].isalnum()
    )


def parse_decisions() -> list[dict]:
    """Parses every decision of `docs/decisions.md`.

    An entry is a top-level bullet that starts with a bold title. Entries with no recorded body of substance are
    ignored.

    Returns:
        All decisions in document order.
    """
    lines = read("docs/decisions.md").splitlines()
    section = ""
    entries: list[dict] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("## "):
            section = line[3:].strip()
        if not line.startswith("- **"):
            index += 1
            continue
        end = index + 1
        while end < len(lines) and lines[end].strip() and not lines[end].startswith(("- ", "#")):
            end += 1
        block = "\n".join(piece.strip() if n else piece for n, piece in enumerate(lines[index:end]))
        index = end
        match = re.match(r"- \*\*(.+?)\*\*\s*(.*)", block, re.S)
        if not match:
            continue
        raw_title, body = match.group(1), match.group(2).strip()
        if len(body) < MIN_DECISION_BODY:
            continue
        attribution = re.search(r"Decided by:?\s*(User|Agent)", block)
        title = clean_title(raw_title)
        body = clean_body(body)
        statement, rationale = split_statement(body)
        if re.match(r"[a-z]", statement) and not re.match(r"[a-z]+[A-Z_(.]", statement):
            # A first sentence that starts mid-sentence cannot state the decision: the title does, the body explains it.
            statement, rationale = title.rstrip(".") + ".", body
        if not is_decision_entry(title, statement):
            continue
        key = entry_key(section, raw_title)
        title = CURATION["titles"].get(key, title)
        if key in CURATION["exclude"]:
            continue
        entries.append({
            "key": key, "title": shorten(title, MAX_TITLE), "statement": statement, "rationale": rationale,
            "type": decision_type(section, title), "section": section,
            "decided_by": attribution.group(1) if attribution else "",
        })
    counts = collections.Counter(entry["title"] for entry in entries)
    for entry in entries:
        if entry["key"] not in CURATION["titles"]:
            entry["title"] = shorten(contextual_title(entry["title"], entry["section"], counts[entry["title"]] > 1), MAX_TITLE)
    seen: collections.Counter[str] = collections.Counter(entry["title"] for entry in entries)
    for entry in entries:
        if seen[entry["title"]] > 1:
            phase = re.search(r"Phases? ([\w.]+)", entry["section"])
            tag = f"Phase {phase.group(1)}" if phase else entry["section"][:30].strip()
            entry["title"] = shorten(f"{entry['title']} ({tag})", MAX_TITLE)
    return entries


def select_decisions(entries: list[dict]) -> list[dict]:
    """Chooses the decisions of the fixture.

    Every entry that records a `Decided by` attribution is a decision. An unattributed entry counts only in the
    original design sections (`FOUNDATIONAL_SECTIONS`), where each bullet is a design choice; elsewhere the log's
    unattributed bullets are findings, bug notes and process remarks.

    Args:
        entries: All parsed decisions in document order.

    Returns:
        At most `DECISION_LIMIT` decisions in document order.
    """
    chosen = [e for e in entries if e["decided_by"] or e["section"] in FOUNDATIONAL_SECTIONS]
    return chosen[:DECISION_LIMIT]


def extract_soc2() -> tuple[dict, list[dict]]:
    """Parses the SOC 2 control matrix into a compliance standard and the policy references per criterion.

    Returns:
        A tuple of (standard, policy file names) where the standard holds one requirement per criterion group
        (`CC1` and so on) with its criteria as children, each carrying its assessed status and the policy files
        cited as evidence.
    """
    groups: list[dict] = []
    group: dict | None = None
    for line in read("docs/soc2/trust-services-criteria-mapping.md").splitlines():
        heading = re.match(r"## ((?:CC\d|C\d)) — (.+)$", line)
        if heading:
            group = {"reference": heading.group(1), "name": heading.group(2).strip(), "criteria": []}
            groups.append(group)
            continue
        row = re.match(r"\| ((?:CC|C)\d+\.\d+) \| (.*) \| (.*) \| (.*) \| (.*) \|$", line)
        if not row or group is None:
            continue
        status_text = row.group(5)
        symbol = next((s for s in STATUS_BY_SYMBOL if s in status_text), "")
        group["criteria"].append({
            "reference": row.group(1), "name": clean_cell(row.group(2)), "control": clean_cell(row.group(3)),
            "evidence": clean_cell(row.group(4)), "status": STATUS_BY_SYMBOL.get(symbol, "not_started"),
            "status_note": re.sub(r"^\S+\s*", "", status_text).strip() if symbol else status_text.strip(),
            "policies": sorted(set(re.findall(r"policies/([a-z0-9-]+)\.md", row.group(4)))),
        })
    policies = [
        {"file": path.stem, "title": next(
            (line[2:].strip() for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("# ")), path.stem
        )}
        for path in sorted((REPO_ROOT / "docs/soc2/policies").glob("*.md"))
    ]
    standard = {
        "reference": "SOC 2", "name": "SOC 2 Trust Services Criteria (Security and Confidentiality)",
        "description": "The 2017 Trust Services Criteria (revised 2022) for Security (CC1 to CC9) and Confidentiality (C1), "
                       "as assessed in docs/soc2/trust-services-criteria-mapping.md.",
        "groups": groups,
    }
    return standard, policies


def extract_gaps() -> list[dict]:
    """Parses each policy's open known gaps (not struck through) into risk records.

    Returns:
        One record per open gap with its policy, title, statement and risk type.
    """
    gaps: list[dict] = []
    for path in sorted((REPO_ROOT / "docs/soc2/policies").glob("*.md")):
        text = path.read_text(encoding="utf-8")
        match = re.search(r"(?ms)^## Known Gaps / Exceptions\s*\n(.*?)(?=^## |\Z)", text)
        if not match:
            continue
        for item in re.finditer(r"(?ms)^\d+\.\s+(.*?)(?=^\d+\.\s|\Z)", match.group(1)):
            body = " ".join(item.group(1).split())
            if body.startswith("~~") or not body:
                continue
            lead = re.match(r"\*\*(.+?)\*\*", body)
            title = lead.group(1) if lead else body.split(". ")[0]
            gaps.append({
                "policy": path.stem, "title": shorten(re.sub(r"[`*]", "", title).strip(" .:—-"), MAX_TITLE),
                "statement": re.sub(r"^\*\*.+?\*\*[\s.:—-]*", "", re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", body)) or title,
                "type": RISK_TYPE_BY_POLICY.get(path.stem, "Security"),
            })
    return gaps


def extract_principles() -> list[dict]:
    """Parses the architecture document's core principles into guiding principles.

    Returns:
        One record per numbered principle with its name and statement.
    """
    text = read("docs/solution-architecture.md")
    section = re.search(r"(?ms)^## Core Architecture Principles\s*\n(.*?)(?=^## )", text)
    if not section:
        return []
    return [
        {"name": match.group(1).strip(), "statement": " ".join(match.group(2).split())}
        for match in re.finditer(r"(?ms)^### \d+\.\s+(.+?)\n(.*?)(?=^### |\Z)", section.group(1))
    ]


def build_fixture() -> dict:
    """Builds the complete fixture from the repository's documents.

    Returns:
        The fixture as a JSON-serialisable dictionary.
    """
    components, requirements, stages = extract_requirements()
    standard, policies = extract_soc2()
    return {
        "version": FIXTURE_VERSION,
        "components": components,
        "requirements": requirements,
        "stages": stages,
        "decisions": select_decisions(parse_decisions()),
        "standard": standard,
        "policies": policies,
        "gaps": extract_gaps(),
        "principles": extract_principles(),
    }


def render(fixture: dict) -> str:
    """Serialises a fixture the way it is committed (in document order).

    Args:
        fixture: The fixture dictionary.

    Returns:
        The JSON text with a trailing newline.
    """
    return json.dumps(fixture, indent=1, ensure_ascii=False) + "\n"


def find_drift(committed: dict, fresh: dict, all_decisions: list[dict]) -> list[str]:
    """Compares the committed fixture with one built from the documents now.

    Everything except the decisions must match exactly. The decisions log only grows, so new entries are not
    drift: each committed decision must still exist unchanged in the log, and an edited or removed one is drift.

    Args:
        committed: The fixture committed to the repository.
        fresh: A fixture built from the documents.
        all_decisions: Every decision parsed from the documents (not only the selected ones).

    Returns:
        One message per difference; empty when the fixture is current.
    """
    problems = [
        f"'{key}' differs from the documents"
        for key in fresh
        if key != "decisions" and committed.get(key) != fresh[key]
    ]
    current = {json.dumps(entry, sort_keys=True) for entry in all_decisions}
    problems += [
        f"decision {entry['title']!r} was edited or removed in docs/decisions.md"
        for entry in committed.get("decisions", [])
        if json.dumps(entry, sort_keys=True) not in current
    ]
    return problems


def main(argv: list[str] | None = None) -> int:
    """Writes the fixture or checks the committed one against the documents.

    Args:
        argv: Command-line arguments (`--write` or `--check`).

    Returns:
        0 on success, 1 when `--check` finds the committed fixture out of date.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1] if __doc__ else "")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="Regenerate the committed fixture.")
    mode.add_argument("--check", action="store_true", help="Fail when the committed fixture is out of date.")
    args = parser.parse_args(argv)
    fresh = build_fixture()
    text = render(fresh)
    if args.write:
        FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE_PATH.write_text(text, encoding="utf-8")
        print(f"Wrote {FIXTURE_PATH.relative_to(REPO_ROOT)}")
        return 0
    problems = (
        find_drift(json.loads(FIXTURE_PATH.read_text(encoding="utf-8")), fresh, parse_decisions())
        if FIXTURE_PATH.exists() else ["the fixture has not been generated"]
    )
    if problems:
        print("The demo fixture is out of date: " + "; ".join(problems), file=sys.stderr)
        print("Run: python backend/scripts/extract_repo_demo.py --write", file=sys.stderr)
        return 1
    print("The demo fixture matches the documents.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
