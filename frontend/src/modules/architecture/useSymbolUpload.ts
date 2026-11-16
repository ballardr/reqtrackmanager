/**
 * Module: modules/architecture/useSymbolUpload
 *
 * Uploading a symbol to a project's or an organisation's library, shared by the Symbols settings panel and the symbol
 * picker so both show the same refusal and success wording. The server's sanitiser is the only gate (it refuses a file that is
 * not an SVG, holds a script or is too large; the upload endpoints need `architecture_admin` or
 * `architecture_org_admin`), so `useCanUploadSymbols` only decides whether the control is offered.
 */
import { useEffect, useState } from "react";

import { toErrorMessage, useToast } from "../../context/ToastContext";
import { capabilitiesApi, symbolApi } from "./api";
import type { TypesScope } from "./ArchitectureTypesPanel";
import type { ArchitectureSymbol } from "./types";

/** What `useSymbolUpload` returns. */
export interface SymbolUpload {
  /** Uploads one file; resolves with the stored symbol, or `null` after showing the refusal in `error`. */
  upload: (file: File) => Promise<ArchitectureSymbol | null>;
  /** The server's reason for refusing the last upload, or `null`. */
  error: string | null;
  /** True while a file is being sent. */
  busy: boolean;
}

/**
 * @param scope The project or organisation whose library receives the file.
 * @param onUploaded Called with the stored symbol after a success (after the toast).
 * @param successMessage The toast's text.
 * @returns The upload action with its error and busy state.
 */
export function useSymbolUpload(
  scope: TypesScope, onUploaded?: (symbol: ArchitectureSymbol) => void, successMessage = "Symbol uploaded.",
): SymbolUpload {
  const { showToast } = useToast();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function upload(file: File): Promise<ArchitectureSymbol | null> {
    setError(null);
    setBusy(true);
    try {
      const stored = await (scope.kind === "project"
        ? symbolApi.projectUpload(scope.projectId, file)
        : symbolApi.orgUpload(scope.organizationId, file));
      showToast(successMessage);
      onUploaded?.(stored);
      return stored;
    } catch (err) {
      setError(toErrorMessage(err, "Could not upload the symbol."));
      return null;
    } finally {
      setBusy(false);
    }
  }

  return { upload, error, busy };
}

/**
 * @param scope The project or organisation a record belongs to, or `null` when the caller cannot say (nothing is offered).
 * @returns True once the capabilities read says the person may change the library; false while it loads or when it fails.
 */
export function useCanUploadSymbols(scope: TypesScope | null): boolean {
  const kind = scope?.kind ?? null;
  const ownerId = scope === null ? null : scope.kind === "project" ? scope.projectId : scope.organizationId;
  const key = kind === null ? null : `${kind}:${ownerId}`;
  const [answer, setAnswer] = useState<{ key: string; allowed: boolean } | null>(null);

  useEffect(() => {
    if (kind === null || ownerId === null || key === null) return;
    let live = true;
    (kind === "project" ? capabilitiesApi.get(ownerId) : capabilitiesApi.orgGet(ownerId))
      .then((c) => c.manage_types)
      .catch(() => false)
      .then((allowed) => { if (live) setAnswer({ key, allowed }); });
    return () => { live = false; };
  }, [kind, ownerId, key]);

  return answer !== null && answer.key === key && answer.allowed;
}
