/**
 * Module: utils/mathTex
 *
 * Which TeX the screen draws and where equations are in a piece of text: the browser counterpart of the report
 * engine's `services/report_math.py` (`tex_problem`, `split_math`), so an equation that would be refused in a
 * report is not drawn on screen either.
 *
 * Responsibilities:
 * - `texProblem`: the command allow-list, read from `mathAllowList.json`, which is generated from the backend
 *   (`backend/scripts/generate_math_allowlist.py`); a backend test fails when the file is out of date.
 * - `splitMath`: find `\( x \)` (inline) and `$$ x $$` (display) in text. A bare `$` is never a delimiter, and an
 *   opener without a closer is ordinary text.
 *
 * Design decisions:
 * - The algorithm is ported by hand, so `mathTexCases.json` holds test vectors that the backend test and
 *   `mathTex.stories.tsx` both run: a change to one side that the other does not follow fails a test.
 * - KaTeX itself is stricter than nothing (`trust: false`) but wider than the report allow-list (it accepts
 *   `\def`, for one); this check is what keeps the two screens consistent.
 */
import allowList from "./mathAllowList.json";

const COMMANDS = new Set<string>(allowList.commands);
const SYMBOL_COMMANDS = new Set<string>(allowList.symbolCommands);
const ENVIRONMENTS = new Set<string>(allowList.environments);
const TEXT_COMMANDS = new Set<string>(allowList.textCommands);
const FORBIDDEN = new Set<string>(Array.from(allowList.forbiddenCharacters));
const PLAIN_TEXT = new RegExp(`^(?:${allowList.plainTextPattern})$`);
const ASCII_LETTER = /[A-Za-z]/;
const INVISIBLE = /[\p{Cc}\p{Cf}\p{Cs}\p{Co}\p{Cn}]/u;
const ENVIRONMENT = /^\{([A-Za-z]+)\}/;

/** Why `tex` may not be drawn, or `null` when it passes the allow-list (the same rules as the report engine). */
export function texProblem(tex: string): string | null {
  if (!tex.trim()) return "The equation is empty.";
  if (tex.length > allowList.maxChars) return `An equation is limited to ${allowList.maxChars} characters.`;
  const environments: string[] = [];
  let depth = 0;
  let i = 0;
  while (i < tex.length) {
    const ch = tex[i];
    if (FORBIDDEN.has(ch)) return `The character ${ch} is not supported in equations.`;
    if (!/\s/u.test(ch) && INVISIBLE.test(ch)) return "An equation may not contain control or invisible characters.";
    if (ch === "{") {
      depth += 1;
      if (depth > allowList.maxDepth) return `Braces are nested more than ${allowList.maxDepth} deep.`;
    } else if (ch === "}") {
      depth -= 1;
      if (depth < 0) return "A } has no matching {.";
    } else if (ch === "&" && environments.length === 0) {
      return "An & is only used inside a matrix, cases or aligned environment.";
    } else if (ch === "\\") {
      const [next, problem] = command(tex, i, environments);
      if (problem) return problem;
      i = next;
      continue;
    }
    i += 1;
  }
  if (depth) return "A { is never closed.";
  if (environments.length) return `\\begin{${environments[environments.length - 1]}} is never closed.`;
  return null;
}

function command(tex: string, start: number, environments: string[]): [number, string | null] {
  const n = tex.length;
  const j = start + 1;
  if (j >= n) return [n, "A backslash must be followed by a command."];
  if (!ASCII_LETTER.test(tex[j])) {
    return SYMBOL_COMMANDS.has(tex[j]) ? [j + 1, null] : [j + 1, `The command \\${tex[j]} is not supported in equations.`];
  }
  let k = j;
  while (k < n && ASCII_LETTER.test(tex[k])) k += 1;
  const name = tex.slice(j, k);
  if (!COMMANDS.has(name)) return [k, `The command \\${name.slice(0, 30)} is not supported in equations.`];
  if (name === "begin" || name === "end") {
    const found = ENVIRONMENT.exec(tex.slice(k));
    if (!found || !ENVIRONMENTS.has(found[1])) return [k, `\\${name} must name one of: ${Array.from(ENVIRONMENTS).sort().join(", ")}.`];
    const end = k + found[0].length;
    if (name === "begin") environments.push(found[1]);
    else if (environments.pop() !== found[1]) return [end, `\\end{${found[1]}} does not match an open \\begin.`];
    return [end, null];
  }
  if (TEXT_COMMANDS.has(name)) {
    let m = k;
    while (m < n && /\s/u.test(tex[m])) m += 1;
    const close = m < n && tex[m] === "{" ? tex.indexOf("}", m) : -1;
    if (close < 0 || !PLAIN_TEXT.test(tex.slice(m + 1, close))) {
      return [k, `\\${name} takes plain text in braces (letters, digits, spaces and basic punctuation).`];
    }
    return [close + 1, null];
  }
  return [k, null];
}

/** One piece of a text: ordinary text, or an `inline` / `display` equation (`value` is the TeX). */
export interface MathSegment {
  kind: "text" | "inline" | "display";
  value: string;
}

const OPENERS = /\\\(|\$\$/g;

/**
 * Splits `text` into ordinary text and equations: `\( x \)` is inline and `$$ x $$` is display. An opener with no
 * closer, or enclosing nothing, stays text. The TeX is not checked here (see `texProblem`).
 */
export function splitMath(text: string): MathSegment[] {
  const segments: MathSegment[] = [];
  let plain = "";
  let cursor = 0;
  for (const opener of text.matchAll(OPENERS)) {
    const start = opener.index ?? 0;
    if (start < cursor) continue;
    const closer = opener[0] === "$$" ? "$$" : "\\)";
    const end = text.indexOf(closer, start + 2);
    if (end < 0 || !text.slice(start + 2, end).trim()) continue;
    plain += text.slice(cursor, start);
    if (plain) segments.push({ kind: "text", value: plain });
    plain = "";
    segments.push({ kind: opener[0] === "$$" ? "display" : "inline", value: text.slice(start + 2, end) });
    cursor = end + closer.length;
  }
  plain += text.slice(cursor);
  if (plain) segments.push({ kind: "text", value: plain });
  return segments;
}

/** The text as the author wrote it: what is shown when an equation cannot be drawn. */
export function mathSource(segment: MathSegment): string {
  if (segment.kind === "text") return segment.value;
  return segment.kind === "display" ? `$$${segment.value}$$` : `\\(${segment.value}\\)`;
}
