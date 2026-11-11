/**
 * Module: utils/safeMarkdown
 *
 * Renders the small markdown subset of the overview's text widget as React elements: headings (`#` to `###`),
 * paragraphs, bullet and numbered lists, quotes, rules, and inline bold, italic, code and links.
 *
 * Design decisions:
 * - The text is written by a project manager or an organisation administrator and read by everyone who opens the
 *   overview, so it is never trusted: there is no raw HTML, no image and no script URL. Everything is built as
 *   elements, so React escapes the text; a link must be `http` or `https` and opens in a new tab with
 *   `rel="noopener noreferrer"`, and anything else is shown as plain text.
 * - A subset on purpose: a note for the page, not a document. An unknown construct is shown as the text typed.
 */
import { Fragment, type ReactNode } from "react";

const LINK = /^\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/;

/** Splits `text` into inline elements: `**bold**`, `*italic*` or `_italic_`, `` `code` `` and `[label](https://…)`. */
function inline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let rest = text;
  let plain = "";
  let index = 0;
  const flush = () => {
    if (plain) nodes.push(plain);
    plain = "";
  };
  while (rest.length > 0) {
    const key = `${keyPrefix}-${index++}`;
    let match: RegExpMatchArray | null;
    if ((match = rest.match(/^`([^`]+)`/))) {
      flush();
      nodes.push(<code key={key}>{match[1]}</code>);
    } else if ((match = rest.match(/^\*\*([^*]+)\*\*/))) {
      flush();
      nodes.push(<strong key={key}>{inline(match[1], key)}</strong>);
    } else if ((match = rest.match(/^(?:\*([^*\s][^*]*)\*|_([^_\s][^_]*)_)/))) {
      flush();
      nodes.push(<em key={key}>{inline(match[1] ?? match[2], key)}</em>);
    } else if ((match = rest.match(LINK))) {
      flush();
      nodes.push(<a key={key} href={match[2]} target="_blank" rel="noopener noreferrer">{match[1]}</a>);
    } else {
      plain += rest[0];
      rest = rest.slice(1);
      continue;
    }
    rest = rest.slice(match[0].length);
  }
  flush();
  return nodes;
}

/**
 * @param markdown The text to render.
 * @returns The rendered blocks, or an empty array for blank text.
 */
export function renderMarkdown(markdown: string): ReactNode[] {
  const lines = markdown.replace(/\r\n?/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let paragraph: string[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  const flushParagraph = () => {
    if (paragraph.length === 0) return;
    const key = `p${blocks.length}`;
    blocks.push(
      <p key={key}>
        {paragraph.map((line, i) => <Fragment key={i}>{i > 0 && <br />}{inline(line, `${key}-${i}`)}</Fragment>)}
      </p>,
    );
    paragraph = [];
  };
  const flushList = () => {
    if (!list) return;
    const key = `l${blocks.length}`;
    const items = list.items.map((item, i) => <li key={i}>{inline(item, `${key}-${i}`)}</li>);
    blocks.push(list.ordered ? <ol key={key}>{items}</ol> : <ul key={key}>{items}</ul>);
    list = null;
  };
  for (const raw of lines) {
    const line = raw.trimEnd();
    let match: RegExpMatchArray | null;
    if (line.trim() === "") {
      flushParagraph();
      flushList();
    } else if ((match = line.match(/^(#{1,3})\s+(.+)$/))) {
      flushParagraph();
      flushList();
      const level = match[1].length;
      const key = `h${blocks.length}`;
      const Tag = (["h3", "h4", "h5"] as const)[level - 1];
      blocks.push(<Tag key={key}>{inline(match[2], key)}</Tag>);
    } else if (/^(-{3,}|\*{3,})$/.test(line.trim())) {
      flushParagraph();
      flushList();
      blocks.push(<hr key={`r${blocks.length}`} />);
    } else if ((match = line.match(/^\s*[-*]\s+(.+)$/))) {
      flushParagraph();
      if (list && list.ordered) flushList();
      list = list ?? { ordered: false, items: [] };
      list.items.push(match[1]);
    } else if ((match = line.match(/^\s*\d+[.)]\s+(.+)$/))) {
      flushParagraph();
      if (list && !list.ordered) flushList();
      list = list ?? { ordered: true, items: [] };
      list.items.push(match[1]);
    } else if ((match = line.match(/^>\s?(.*)$/))) {
      flushParagraph();
      flushList();
      const key = `q${blocks.length}`;
      blocks.push(<blockquote key={key}>{inline(match[1], key)}</blockquote>);
    } else {
      flushList();
      paragraph.push(line);
    }
  }
  flushParagraph();
  flushList();
  return blocks;
}
