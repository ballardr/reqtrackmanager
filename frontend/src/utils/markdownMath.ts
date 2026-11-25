/**
 * Module: utils/markdownMath
 *
 * A markdown-it inline rule that reads equations, so a Markdown field holding
 * mathematics (a requirement's description, reasoning, clarification) can also
 * be formatted. Reads `\( x \)` as inline and `$$ x $$` as display, with the
 * delimiters of the report engine and `utils/mathTex.splitMath`: an opener with
 * no closer, or enclosing nothing, is text, and a bare `$` is never a delimiter.
 * Produces one `math` token (`content` is the TeX, `meta.display` the kind) so
 * its characters are never read as emphasis, escapes or code.
 * Design: the rule runs before `escape` (which would turn `\(` into `(`) and
 * consumes the whole equation, so `x_1 * y_2` stays TeX; code spans and fences
 * are read first by the reader's own rules, so code shows as typed. An equation
 * lives inside one paragraph (the report engine's reader has the same limit).
 * The TeX is not checked here (`utils/mathTex.texProblem` does that when drawn).
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
