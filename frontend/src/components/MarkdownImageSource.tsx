/**
 * Module: components/MarkdownImageSource
 *
 * Tells the Markdown editors under it which attachments a picture may be chosen from, and how a new one is attached.
 *
 * `MarkdownImageSourceProvider`: a record's page supplies the record's attachments and, when the person may attach,
 * the function that attaches a file (`DetailLayout`'s `pictures`). The editors read it through
 * `useMarkdownImageSource`; with no provider (a create form, a comment box, a type with no attachments) they offer
 * no Picture button, because there is no record to attach to.
 *
 * A picture is always an attachment of the record being edited, so the source is the page's own attachment list
 * and upload call: a picture inserted from a fresh upload shows in the Attachments card too. `upload` is absent
 * while attachments are locked or the person cannot attach; the picker then offers no upload.
 */
import { useMemo, type ReactNode } from "react";

import { MarkdownImageSourceContext, type MarkdownImageSource } from "./markdownImageSourceContext";

/**
 * @param files The record's attachments.
 * @param upload Attaches a file to the record (absent when attachments cannot be added now).
 * @param children The record's page (its forms and modals are inside it).
 */
export function MarkdownImageSourceProvider({ files, upload, children }: MarkdownImageSource & { children: ReactNode }) {
  const value = useMemo(() => ({ files, upload }), [files, upload]);
  return <MarkdownImageSourceContext.Provider value={value}>{children}</MarkdownImageSourceContext.Provider>;
}
