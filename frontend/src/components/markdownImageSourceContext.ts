/**
 * Module: components/markdownImageSourceContext
 *
 * The context behind `MarkdownImageSourceProvider`: which attachments a picture in a Markdown field may be chosen from,
 * and how a new one is attached. Kept apart from the provider component so the editors can read it without a
 * component file exporting a hook.
 */
import { createContext, useContext } from "react";

import type { FileAsset } from "../api/types";

export interface MarkdownImageSource {
  /** The record's attachments (the picker lists the pictures among them). */
  files: FileAsset[];
  /** Attaches a file to the record and resolves to the new attachment; absent when the person cannot attach. */
  upload?: (file: File) => Promise<FileAsset>;
}

export const MarkdownImageSourceContext = createContext<MarkdownImageSource | null>(null);

/** @returns The enclosing record's picture source, or `null` when there is none. */
export function useMarkdownImageSource(): MarkdownImageSource | null {
  return useContext(MarkdownImageSourceContext);
}
