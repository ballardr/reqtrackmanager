/**
 * Module: components/ReportLayoutVariablesField
 *
 * The layout's run-time variables in the outline: the same declaration editor a report pack uses
 * (`ReportPackVariablesEditor`), because a pack variable is declared exactly as a layout's is.
 *
 * Responsibilities: give the shared editor the client-only ids it keys rows by, and hand the layout back a plain
 * list of declarations (or none, so the saved tree has no empty `variables` key).
 */
import { useState } from "react";

import type { ReportFieldCatalogue } from "../api/reportLayouts";
import type { PackVariableDeclaration } from "../api/reportPacks";
import { useStrings } from "../context/TerminologyContext";
import { newUid } from "../utils/reportPackDraft";
import { ReportPackVariablesEditor, type DraftVariable } from "./ReportPackVariablesEditor";

/**
 * @param value The declarations as stored (`undefined` for none).
 * @param onChange Called with the edited declarations, `undefined` when none are left.
 * @param catalogue The record types and fields a variable's options can come from.
 * @param disabled Read-only.
 */
export function ReportLayoutVariablesField({
  value, onChange, catalogue, disabled,
}: {
  value: PackVariableDeclaration[] | undefined;
  onChange: (next: PackVariableDeclaration[] | undefined) => void;
  catalogue: ReportFieldCatalogue | null;
  disabled?: boolean;
}) {
  const text = useStrings().reportOutline;
  const declared = value ?? [];
  const [uids, setUids] = useState<string[]>(() => declared.map(() => newUid()));
  // A change from outside (another view, a restored version) may add or drop rows: keep one id per row.
  const ids = declared.map((_, i) => uids[i] ?? `row-${i}`);
  const drafts: DraftVariable[] = declared.map((variable, i) => ({ uid: ids[i], variable }));

  return (
    <ReportPackVariablesEditor
      variables={drafts} catalogue={catalogue} disabled={disabled} intro={text.variablesIntro} emptyText={text.noVariables}
      onChange={(next) => {
        setUids(next.map((d) => d.uid));
        onChange(next.length === 0 ? undefined : next.map((d) => d.variable));
      }}
    />
  );
}
