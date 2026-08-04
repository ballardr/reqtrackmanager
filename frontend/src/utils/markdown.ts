/**
 * A small, deliberately minimal Markdown-to-HTML renderer — headings,
 * paragraphs, bullet lists, fenced code blocks, and inline
 * bold/italic/code/links. Mirrors the same subset
 * `backend/app/services/reports.py`'s Markdown-to-flowable renderer
 * supports (plus fenced code blocks, which that renderer doesn't need),
 * and exists for the same reason: enough fidelity for hand-written
 * content (the help page, `frontend/src/help/*.md`) without pulling in a
 * full Markdown/HTML-sanitiser dependency this otherwise dependency-light
 * frontend doesn't have.
 *
 * A ```mermaid fenced block renders as `<div class="mermaid">` (raw,
 * unescaped diagram source) — the exact convention `mermaid.run()` scans
 * the page for, so the caller just needs to call that once after this
 * function's output is in the DOM (see `pages/HelpPage.tsx`). Any other
 * language tag renders as an ordinary escaped `<pre><code>` block.
 *
 * Input is always developer-authored static content checked into the
 * repo, never user input — but raw HTML in a non-mermaid code block, and
 * in every other kind of line, is still escaped first, so this never
 * becomes an HTML-injection foothold if that ever changes. Mermaid source
 * is deliberately the one exception (mermaid's own parser needs the raw
 * text, not HTML-escaped entities) — still safe, since it's the same
 * developer-authored-only content, rendered by mermaid's own sandboxed
 * SVG generation rather than injected as arbitrary HTML.
 */

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderInline(text: string): string {
  return escapeHtml(text)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
}

export function renderMarkdown(source: string): string {
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  const html: string[] = [];
  let paragraph: string[] = [];
  let listItems: string[] = [];
  let codeLang: string | null = null;
  let codeLines: string[] = [];

  function flushParagraph() {
    if (paragraph.length > 0) {
      html.push(`<p>${renderInline(paragraph.join(" "))}</p>`);
      paragraph = [];
    }
  }

  function flushList() {
    if (listItems.length > 0) {
      html.push(`<ul>${listItems.map((item) => `<li>${renderInline(item)}</li>`).join("")}</ul>`);
      listItems = [];
    }
  }

  for (const rawLine of lines) {
    const line = rawLine.trim();
    const fenceMatch = line.match(/^```\s*(\S*)\s*$/);

    if (codeLang !== null) {
      if (fenceMatch) {
        // Closing fence.
        html.push(
          codeLang === "mermaid"
            ? `<div class="mermaid">${codeLines.join("\n")}</div>`
            : `<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`
        );
        codeLang = null;
        codeLines = [];
      } else {
        codeLines.push(rawLine);
      }
      continue;
    }

    const headingMatch = line.match(/^(#{1,6})\s+(.*)$/);
    const bulletMatch = line.match(/^[-*]\s+(.*)$/);

    if (fenceMatch) {
      flushParagraph();
      flushList();
      codeLang = fenceMatch[1] || "";
    } else if (headingMatch) {
      flushParagraph();
      flushList();
      const level = headingMatch[1].length;
      html.push(`<h${level}>${renderInline(headingMatch[2])}</h${level}>`);
    } else if (bulletMatch) {
      flushParagraph();
      listItems.push(bulletMatch[1]);
    } else if (line === "") {
      flushParagraph();
      flushList();
    } else {
      flushList();
      paragraph.push(line);
    }
  }
  flushParagraph();
  flushList();
  // An unterminated fence (a stray trailing ``` never closed) — render
  // whatever was captured rather than silently dropping it.
  if (codeLang !== null && codeLines.length > 0) {
    html.push(
      codeLang === "mermaid"
        ? `<div class="mermaid">${codeLines.join("\n")}</div>`
        : `<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`
    );
  }

  return html.join("\n");
}

function serializeInline(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) {
    return node.textContent ?? "";
  }
  if (node.nodeType !== Node.ELEMENT_NODE) return "";
  const el = node as HTMLElement;
  const inner = Array.from(el.childNodes).map(serializeInline).join("");
  switch (el.tagName) {
    case "STRONG":
    case "B":
      return inner.trim() ? `**${inner}**` : inner;
    case "EM":
    case "I":
      return inner.trim() ? `*${inner}*` : inner;
    case "CODE":
      return `\`${inner}\``;
    case "A": {
      const href = el.getAttribute("href") ?? "";
      return `[${inner}](${href})`;
    }
    case "BR":
      return "\n";
    default:
      return inner;
  }
}

/**
 * The reverse of `renderMarkdown` — walks a live DOM subtree (a
 * `contentEditable` container's children, in practice — see
 * `components/RichTextEditor.tsx`) back into the same Markdown subset.
 * Deliberately tolerant of `<div>`-wrapped lines (what `contentEditable`
 * editing actually produces in most browsers, rather than clean `<p>`s) by
 * treating any unrecognised block-level element as a paragraph.
 */
export function htmlToMarkdown(container: HTMLElement): string {
  const blocks: string[] = [];
  for (const child of Array.from(container.childNodes)) {
    if (child.nodeType === Node.TEXT_NODE) {
      const text = child.textContent?.trim();
      if (text) blocks.push(text);
      continue;
    }
    if (child.nodeType !== Node.ELEMENT_NODE) continue;
    const el = child as HTMLElement;
    const headingLevel = el.tagName.match(/^H([1-6])$/)?.[1];

    if (headingLevel) {
      const text = serializeInline(el).trim();
      if (text) blocks.push(`${"#".repeat(Number(headingLevel))} ${text}`);
    } else if (el.tagName === "UL" || el.tagName === "OL") {
      const lines = Array.from(el.children)
        .filter((c) => c.tagName === "LI")
        .map((li) => `- ${serializeInline(li).trim()}`)
        .filter((line) => line !== "- ");
      if (lines.length > 0) blocks.push(lines.join("\n"));
    } else if (el.tagName === "PRE") {
      blocks.push("```\n" + (el.textContent ?? "") + "\n```");
    } else {
      const text = serializeInline(el).trim();
      if (text) blocks.push(text);
    }
  }
  return blocks.join("\n\n");
}
