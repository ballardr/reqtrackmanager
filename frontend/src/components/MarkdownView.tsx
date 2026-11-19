/**
 * Module: components/MarkdownView
 *
 * Shows Markdown text (a decision, a note, any long text field that is written in Markdown) as read-only content.
 *
 * Responsibilities:
 * - Turn the reader's tokens (`utils/markdownIt`) into React elements: headings, paragraphs, lists, quotations,
 *   tables, code, rules, emphasis, links, and a fenced `mermaid` block as a diagram (`MermaidDiagram`).
 *
 * Design decisions:
 * - Nothing is inserted as HTML (as `PolicyBodyView`), so stored text can never run as markup; raw HTML in the text
 *   is shown as text, an image is shown as the text typed, and only https, http and mailto addresses are links.
 * - Headings start at the third level (`#` is an `h3`), because the page that shows the text already owns the first
 *   two; deeper levels stop at the sixth.
 * - A link opens in a new tab with `rel="noopener noreferrer"`.
 */
import { Fragment, useMemo, type ReactNode } from "react";

import { isMermaidFence, parseMarkdown, type Token } from "../utils/markdownIt";
import { MermaidDiagram } from "./MermaidDiagram";

interface Node {
  token: Token;
  children: Node[];
}

/** Builds the element tree from the flat token list (opening tokens nest what follows until their closing token). */
function buildTree(tokens: Token[]): Node[] {
  const root: Node = { token: tokens[0], children: [] };
  const stack: Node[] = [root];
  for (const token of tokens) {
    const parent = stack[stack.length - 1];
    if (token.nesting === 1) {
      const node: Node = { token, children: [] };
      parent.children.push(node);
      stack.push(node);
    } else if (token.nesting === -1) {
      if (stack.length > 1) stack.pop();
    } else {
      parent.children.push({ token, children: [] });
    }
  }
  return root.children;
}

function alignOf(token: Token): "left" | "center" | "right" | undefined {
  const style = String(token.attrGet("style") ?? "");
  const match = style.match(/text-align:\s*(left|center|right)/);
  return match ? (match[1] as "left" | "center" | "right") : undefined;
}

function renderInline(tokens: Token[], key: string): ReactNode[] {
  return renderNodes(buildTree(tokens), key);
}

function renderNodes(nodes: Node[], key: string): ReactNode[] {
  return nodes.map((node, i) => renderNode(node, `${key}-${i}`));
}

function renderNode(node: Node, key: string): ReactNode {
  const { token } = node;
  const children = () => renderNodes(node.children, key);
  switch (token.type) {
    case "inline": return <Fragment key={key}>{renderInline(token.children ?? [], key)}</Fragment>;
    case "text": return <Fragment key={key}>{token.content}</Fragment>;
    case "softbreak":
    case "hardbreak": return <br key={key} />;
    case "code_inline": return <code key={key}>{token.content}</code>;
    case "paragraph_open": return token.hidden ? <Fragment key={key}>{children()}</Fragment> : <p key={key}>{children()}</p>;
    case "heading_open": {
      const level = Math.min(Number(token.tag.slice(1)) + 2, 6);
      const Tag = `h${level}` as "h3";
      return <Tag key={key}>{children()}</Tag>;
    }
    case "bullet_list_open": return <ul key={key}>{children()}</ul>;
    case "ordered_list_open": return <ol key={key} start={Number(token.attrGet("start")) || 1}>{children()}</ol>;
    case "list_item_open": return <li key={key}>{children()}</li>;
    case "blockquote_open": return <blockquote key={key}>{children()}</blockquote>;
    case "table_open": return <div key={key} className="markdown-table"><table>{children()}</table></div>;
    case "thead_open": return <thead key={key}>{children()}</thead>;
    case "tbody_open": return <tbody key={key}>{children()}</tbody>;
    case "tr_open": return <tr key={key}>{children()}</tr>;
    case "th_open": return <th key={key} scope="col" style={{ textAlign: alignOf(token) }}>{children()}</th>;
    case "td_open": return <td key={key} style={{ textAlign: alignOf(token) }}>{children()}</td>;
    case "strong_open": return <strong key={key}>{children()}</strong>;
    case "em_open": return <em key={key}>{children()}</em>;
    case "s_open": return <s key={key}>{children()}</s>;
    case "link_open": {
      const href = String(token.attrGet("href") ?? "");
      return <a key={key} href={href} target="_blank" rel="noopener noreferrer">{children()}</a>;
    }
    case "hr": return <hr key={key} />;
    case "image": return <Fragment key={key}>{`![${token.content}](${String(token.attrGet("src") ?? "")})`}</Fragment>;
    case "fence":
    case "code_block": {
      if (isMermaidFence(token)) return <MermaidDiagram key={key} source={token.content} />;
      const language = token.type === "fence" ? token.info.trim().split(/\s+/)[0] : "";
      return <pre key={key}><code className={language ? `language-${language}` : undefined}>{token.content}</code></pre>;
    }
    default: return <Fragment key={key}>{children()}</Fragment>;
  }
}

/**
 * @param text The Markdown source, as stored.
 * @param className Extra class for the wrapper (a page's own spacing rules).
 */
export function MarkdownView({ text, className }: { text: string; className?: string }) {
  const content = useMemo(() => {
    const tokens = parseMarkdown(text);
    return tokens.length === 0 ? [] : renderNodes(buildTree(tokens), "m");
  }, [text]);
  if (content.length === 0) return null;
  return <div className={`markdown-view${className ? ` ${className}` : ""}`}>{content}</div>;
}
