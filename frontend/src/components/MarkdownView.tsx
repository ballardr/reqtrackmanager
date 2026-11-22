/**
 * Module: components/MarkdownView
 *
 * Shows Markdown text (a decision, a note, any long text field that is written in Markdown) as read-only content.
 *
 * Responsibilities:
 * - Turn the reader's tokens (`utils/markdownIt`) into React elements: headings, paragraphs, lists, quotations,
 *   tables, code, rules, emphasis, links, a fenced `mermaid` block as a diagram (`MermaidDiagram`), a picture of the
 *   record's own attachment (`MarkdownPicture`) and, when asked (`math`), an equation (`MathEquation`).
 *
 * Design decisions:
 * - Nothing is inserted as HTML (as `PolicyBodyView`), so stored text can never run as markup; raw HTML in the text
 *   is shown as text, only https, http and mailto addresses are links, and the only image drawn is an attachment of the
 *   record (`attachment:<file id>`); any other image (an outside address) is shown as the text typed.
 * - Headings start at the third level (`#` is an `h3`), because the page that shows the text already owns the first
 *   two; deeper levels stop at the sixth.
 * - A link opens in a new tab with `rel="noopener noreferrer"`.
 */
import { Fragment, lazy, Suspense, useMemo, type ReactNode } from "react";

import { isMermaidFence, parseMarkdown, SAFE_LINK, type Token } from "../utils/markdownIt";
import { attachmentFileId } from "../utils/markdownPicture";
import { imageAlt } from "../utils/markdownPlain";
import { MarkdownPicture } from "./MarkdownPicture";
import { MermaidDiagram } from "./MermaidDiagram";

// KaTeX is downloaded when a document with an equation is first shown, not with every page that shows Markdown.
const MathEquation = lazy(() => import("./MathEquation").then((module) => ({ default: module.MathEquation })));

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
    case "math": {
      const display = Boolean((token.meta as { display?: boolean } | null)?.display);
      const typed = display ? `$$${token.content}$$` : `\\(${token.content}\\)`;
      return (
        <Suspense key={key} fallback={<>{typed}</>}>
          <MathEquation tex={token.content} display={display} />
        </Suspense>
      );
    }
    case "paragraph_open": {
      if (token.hidden) return <Fragment key={key}>{children()}</Fragment>;
      // A paragraph that is only a picture is a figure (a figure cannot sit inside a paragraph).
      const only = node.children[0]?.token.children;
      const picture = only?.length === 1 && only[0].type === "image" ? attachmentFileId(String(only[0].attrGet("src") ?? "")) : null;
      if (picture && only) {
        return <MarkdownPicture key={key} fileId={picture} alt={imageAlt(only[0])} caption={String(only[0].attrGet("title") ?? "")} block />;
      }
      return <p key={key}>{children()}</p>;
    }
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
      // The reader also accepts an attachment address (for a picture); as a link it is only its text.
      if (!SAFE_LINK.test(href)) return <Fragment key={key}>{children()}</Fragment>;
      return <a key={key} href={href} target="_blank" rel="noopener noreferrer">{children()}</a>;
    }
    case "hr": return <hr key={key} />;
    case "image": {
      const src = String(token.attrGet("src") ?? "");
      const fileId = attachmentFileId(src);
      if (fileId === null) return <Fragment key={key}>{`![${token.content}](${src})`}</Fragment>;
      return <MarkdownPicture key={key} fileId={fileId} alt={imageAlt(token)} caption={String(token.attrGet("title") ?? "")} />;
    }
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
 * @param math Also draw `\( x \)` and `$$ x $$` as equations (the fields people write mathematics in).
 */
export function MarkdownView({ text, className, math }: { text: string; className?: string; math?: boolean }) {
  const content = useMemo(() => {
    const tokens = parseMarkdown(text, { math });
    return tokens.length === 0 ? [] : renderNodes(buildTree(tokens), "m");
  }, [text, math]);
  if (content.length === 0) return null;
  return <div className={`markdown-view${className ? ` ${className}` : ""}`}>{content}</div>;
}
