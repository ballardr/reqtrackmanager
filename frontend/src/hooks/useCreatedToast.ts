/**
 * Module: hooks/useCreatedToast
 *
 * The confirmation after a record is created from a list: it names the record by its code and offers **Open**, so a
 * person who cannot see the new record in the list (an order or a filter puts it elsewhere) can reach it at once
 * (docs/ux-style-guide.md, "Pattern: list sort").
 *
 * Responsibilities:
 * - Build the toast text with the code as the person's own preference shows it (`useRecordCode`).
 * - Link to the record's page through the registered artefact path (`getArtefactPath`), so no module names another's route.
 *
 * Design decisions:
 * - A type with no registered page gets the text without a link rather than a dead button.
 * - The link is a toast action, so it dismisses the toast and the person is not left with a stale message.
 *
 * Dependencies: `ToastContext`, `useRecordCode`, `modules/artefactPaths`.
 */
import { useCallback } from "react";
import { useNavigate } from "react-router-dom";

import { useToast } from "../context/ToastContext";
import { t } from "../i18n/strings";
import { getArtefactPath } from "../modules/artefactPaths";
import { useRecordCode } from "./useRecordCode";

const strings = t();

/**
 * @param projectId The project the record is created in (an empty string until known; no link is offered then).
 * @param artefactType The registered artefact type of the record (`decision`).
 * @returns `(noun, record, verb?)`: shows `Decision DEC-004 created.` with an **Open DEC-004** action (named by the code, so it
 *   never reads as the status "Open" beside it). `verb` replaces
 *   `created` where the record is logged or raised.
 */
export function useCreatedToast(projectId: string, artefactType: string) {
  const { showToast } = useToast();
  const navigate = useNavigate();
  const { code } = useRecordCode();
  return useCallback(
    (noun: string, record: { id: string; unique_code: string }, verb: string = strings.createdToast.created) => {
      const path = projectId ? getArtefactPath(artefactType, projectId, record.id) : null;
      const shown = record.unique_code ? code(record.unique_code) : "";
      showToast(strings.createdToast.text(noun, shown, verb), "success", path
        ? { action: { label: strings.createdToast.open(shown), onClick: () => navigate(path) } }
        : undefined);
    },
    [showToast, navigate, code, projectId, artefactType],
  );
}
