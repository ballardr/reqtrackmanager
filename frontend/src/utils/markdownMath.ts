/**
 * Module: utils/markdownMath
 *
 * A markdown-it inline rule that reads equations, so a Markdown field that holds mathematics (a requirement's
 * description, reasoning and clarification) can also be formatted.
 *
 * Responsibilities:
 * - Read `\( x \)` as an inline equation and `$$ x $$` as a display equation, with the delimiters the report engine
 *   and `utils/mathTex.splitMath` use: an opener with no closer, or enclosing nothing, is ordinary text, and a bare
 *   `$` is never a delimiter.
 * - Produce one `math` token (`content` is the TeX, `meta.display` the kind), so the equation's characters are never
 *   read as emphasis, escapes or code.
 *
 * Design decisions:
 * - The rule runs before `escape` (which would turn `\(` into `(`) and consumes the whole equation, so `x_1 * y_2`
 *   inside it stays TeX. A code span or fenced block that holds the delimiters is read first by the reader's own
 *   rules (they start earlier in the line or are block-level), so code is still shown as typed.
 * - An equation lives inside one paragraph: the inline reader never sees a blank line, so an equation spanning
 *   paragraphs is not one (the report engine's reader has the same limit).
 * - The TeX is not checked here (`utils/mathTex.texProblem` does that when it is drawn).
 */
import type { MarkdownIt, StateInline } from "markdown-it";

/** Registers the equation rule on a reader. */
export function mathPlugin(reader: MarkdownIt): void {
  reader.inline.ruler.before("escape", "math", (state: StateInline, silent: boolean) => {
    const { src, pos } = state;
    let closer: string;
    let display: boolean;
    if (src.startsWith("$$", pos)) {
      closer = "$$";
      display = true;
    } else if (src.startsWith("\\(", pos)) {
      closer = "\\)";
      display = false;
    } else {
      return false;
    }
    const end = src.indexOf(closer, pos + 2);
    if (end < 0 || !src.slice(pos + 2, end).trim()) return false;
    if (!silent) {
      const token = state.push("math", "", 0);
      token.content = src.slice(pos + 2, end);
      token.meta = { display };
    }
    state.pos = end + closer.length;
    return true;
  });
}
