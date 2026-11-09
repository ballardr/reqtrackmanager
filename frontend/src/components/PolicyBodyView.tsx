/**
 * Module: components/PolicyBodyView
 *
 * Renders a policy body (the limited rich-text document the server validates) as read-only content.
 *
 * Design decisions:
 * - Each node becomes a React element from a fixed vocabulary; nothing is inserted as HTML, so a stored value can
 *   never run as markup. A node or mark outside the vocabulary renders its children as plain content.
 * - A link opens in a new tab with `rel="noopener noreferrer"`, and only an https, http or mailto address is
 *   rendered as a link (the server also refuses others).
 */
import type { ReactNode } from "react";

import type { PolicyBody, PolicyNode } from "../api/types";

const SAFE_LINK = /^(https?:|mailto:)/i;

function renderText(node: PolicyNode, key: number): ReactNode {
  let out: ReactNode = node.text ?? "";
  for (const mark of node.marks ?? []) {
    if (mark.type === "bold") out = <strong>{out}</strong>;
    else if (mark.type === "italic") out = <em>{out}</em>;
    else if (mark.type === "link" && mark.attrs?.href && SAFE_LINK.test(mark.attrs.href)) {
      out = <a href={mark.attrs.href} target="_blank" rel="noopener noreferrer">{out}</a>;
    }
  }
  return <span key={key} style={{ display: "contents" }}>{out}</span>;
}

function renderNodes(nodes: PolicyNode[] | undefined): ReactNode[] {
  return (nodes ?? []).map((node, index) => renderNode(node, index));
}

function renderNode(node: PolicyNode, key: number): ReactNode {
  switch (node.type) {
    case "text":
      return renderText(node, key);
    case "paragraph":
      return <p key={key}>{renderNodes(node.content)}</p>;
    case "heading": {
      const level = Number(node.attrs?.level);
      const children = renderNodes(node.content);
      if (level === 1) return <h2 key={key}>{children}</h2>;
      if (level === 2) return <h3 key={key}>{children}</h3>;
      return <h4 key={key}>{children}</h4>;
    }
    case "bulletList":
      return <ul key={key}>{renderNodes(node.content)}</ul>;
    case "orderedList":
      return <ol key={key} start={Number(node.attrs?.start) || 1}>{renderNodes(node.content)}</ol>;
    case "listItem":
      return <li key={key}>{renderNodes(node.content)}</li>;
    case "blockquote":
      return <blockquote key={key}>{renderNodes(node.content)}</blockquote>;
    case "horizontalRule":
      return <hr key={key} />;
    case "hardBreak":
      return <br key={key} />;
    default:
      return <span key={key}>{renderNodes(node.content)}</span>;
  }
}

/**
 * @param body The validated policy document.
 */
export function PolicyBodyView({ body }: { body: PolicyBody }) {
  return <div className="policy-body">{renderNodes(body.content)}</div>;
}
