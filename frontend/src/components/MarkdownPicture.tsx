/**
 * Module: components/MarkdownPicture
 *
 * A picture inside a record's Markdown text, drawn from the attachment it names.
 *
 * Responsibilities:
 * - Draw `![alt](attachment:<file id> "caption")` as an image fetched from the authenticated file endpoint (`fileUrl`), lazily, never wider than its text and never taller than `MAX_HEIGHT`; a captioned picture on a line of its own is a
 *   figure with its caption below.
 * - Show the alternative text (or a stated "unavailable" label) in its place when the file cannot be loaded: it was
 *   removed, the viewer has no access, or the file is not a picture.
 *
 * Design decisions:
 * - The address is built from the file id only, so a stored text can never make the page request another site; the
 *   file endpoint applies the record's access rules.
 * - An `<img>` never runs script, so an uploaded vector drawing is safe to show this way; the file endpoint serves it
 *   with its own content type and `nosniff`.
 * - A plain `<img>`, not `PictureImage`: that component reads the signed-in person's backdrop preference, and Markdown is
 *   shown in places with no signed-in context. A picture is shown as it is.
 * - The failure state is the alternative text in a muted frame, so a screen reader and a sighted person both get words.
 */
import { useState } from "react";

import { fileUrl } from "../api/client";
import { useStrings } from "../context/TerminologyContext";

/**
 * @param fileId The attachment's file id.
 * @param alt The alternative text (may be empty).
 * @param caption The caption (may be empty).
 * @param block Whether the picture is on a line of its own (a figure when captioned); false inside a sentence.
 */
export function MarkdownPicture({ fileId, alt, caption, block }: { fileId: string; alt: string; caption?: string; block?: boolean }) {
  const text = useStrings().richText;
  const [failed, setFailed] = useState(false);
  const picture = failed ? (
    <span className="markdown-picture markdown-picture--missing" role="img" aria-label={alt || text.pictureUnavailable}>
      {alt || text.pictureUnavailable}
    </span>
  ) : (
    <img className="markdown-picture" src={fileUrl(fileId)} alt={alt} title={block ? undefined : caption || undefined} loading="lazy" onError={() => setFailed(true)} />
  );
  if (!block) return picture;
  return caption ? <figure className="markdown-figure">{picture}<figcaption>{caption}</figcaption></figure> : <div className="markdown-figure">{picture}</div>;
}
