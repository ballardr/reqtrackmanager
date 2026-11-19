/**
 * Module: components/RecordCodePrefixPanel
 *
 * Administration of the prefix new records are numbered with, for one tier: Organisation Admin (the default every
 * {project} of the organisation starts from) and Project Admin (the {project}'s own prefixes, with the value inherited
 * from a parent {project} or the organisation shown as the placeholder). Each row is one record type: its name, an
 * input for the prefix, where the inherited value comes from, and a control that returns to the inherited value.
 *
 * Design decisions:
 * - One request per row (a prefix is checked against the other types' prefixes in the same scope, so rows are not
 *   saved as a batch: a swap of two prefixes is two ordered changes the person makes deliberately).
 * - The server owns every rule (shape, uniqueness, nesting); the input only blocks what can never be valid (not two to
 *   five letters) and shows the server's message on a refusal.
 * - A change affects records created afterwards only; this is stated in the column help, not in the layout.
 *
 * Dependencies: `GET/PUT/DELETE /api/v1/orgs/{id}/code-prefixes` and `/api/v1/projects/{id}/code-prefixes`.
 */
import { RotateCcw } from "lucide-react";
import { useCallback, useState } from "react";

import { api } from "../api/client";
import type { CodePrefixRow } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage } from "../context/ToastContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { useMutation } from "../hooks/useMutation";
import { FieldHelp } from "./FieldHelp";
import { InlineTextInput } from "./FormFields";
import { Spinner } from "./Spinner";
import { Tooltip } from "./Tooltip";

/** Where the panel reads and writes: an organisation's defaults, or one project's own prefixes. */
export type CodePrefixScope = { kind: "organization"; organizationId: string } | { kind: "project"; projectId: string };

/** The longest prefix the server accepts. */
const MAX_PREFIX_LENGTH = 5;
const PREFIX_SHAPE = /^[A-Z]{2,5}$/;

function basePath(scope: CodePrefixScope): string {
  return scope.kind === "organization"
    ? `/api/v1/orgs/${scope.organizationId}/code-prefixes`
    : `/api/v1/projects/${scope.projectId}/code-prefixes`;
}

/**
 * @param scope The tier to administer.
 * @param canEdit Whether the person may change prefixes (an organisation administrator or a project manager); the
 *   rows are read-only otherwise.
 */
export function RecordCodePrefixPanel({ scope, canEdit = true }: { scope: CodePrefixScope; canEdit?: boolean }) {
  const strings = useStrings();
  const run = useMutation();
  const [rows, setRows] = useState<CodePrefixRow[] | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [loadError, setLoadError] = useState<string | null>(null);
  const path = basePath(scope);

  const reload = useCallback(async () => {
    try {
      setRows(await api.get<CodePrefixRow[]>(path));
      setDraft({});
      setLoadError(null);
    } catch (err) {
      setLoadError(toErrorMessage(err, strings.codePrefixes.loadFailed));
    }
  }, [path, strings.codePrefixes.loadFailed]);

  useLoadOnChange(reload, [path]);

  async function save(row: CodePrefixRow) {
    const value = draft[row.artefact_type];
    if (value === undefined) return;
    if (await run(() => api.put(`${path}/${row.artefact_type}`, { prefix: value }), "save", strings.codePrefixes.noun)) {
      await reload();
    }
  }

  async function restore(row: CodePrefixRow) {
    if (await run(() => api.delete(`${path}/${row.artefact_type}`), "reset", strings.codePrefixes.noun)) {
      await reload();
    }
  }

  if (loadError) return <div style={{ color: "var(--color-danger)" }}>{loadError}</div>;
  if (!rows) return <Spinner />;
  if (rows.length === 0) return <p className="text-muted" style={{ margin: 0 }}>{strings.codePrefixes.empty}</p>;
  return (
    <table className="table" aria-label={strings.codePrefixes.heading}>
      <thead>
        <tr>
          <th>{strings.codePrefixes.recordType}</th>
          <th>
            <span className="field-caption">
              <span>{strings.codePrefixes.prefix}</span>
              <FieldHelp label={strings.codePrefixes.prefix} help={strings.help.recordCodePrefix} />
            </span>
          </th>
          <th />
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => {
          const value = draft[row.artefact_type] ?? row.own_prefix ?? "";
          const dirty = draft[row.artefact_type] !== undefined && draft[row.artefact_type] !== (row.own_prefix ?? "");
          const valid = PREFIX_SHAPE.test(value);
          const inheritedNote = row.own_prefix === null && !value
            ? row.inherited_source === "parent_project" ? strings.codePrefixes.fromParent
              : row.inherited_source === "organization" ? strings.codePrefixes.fromOrganisation : null
            : null;
          return (
            <tr key={row.artefact_type} data-artefact-type={row.artefact_type}>
              <td>{row.label}</td>
              <td>
                <InlineTextInput
                  ariaLabel={strings.codePrefixes.prefixOf(row.label)} value={value} placeholder={row.inherited_prefix}
                  maxWidth={120} disabled={!canEdit}
                  onChange={(next) => setDraft((d) => ({ ...d, [row.artefact_type]: next.toUpperCase().slice(0, MAX_PREFIX_LENGTH) }))}
                />
                {inheritedNote && (
                  <span className="text-muted" style={{ marginLeft: "var(--space-2)" }}>{inheritedNote}</span>
                )}
              </td>
              <td>
                {canEdit && (
                  <span className="row" style={{ gap: "var(--space-2)", justifyContent: "flex-end" }}>
                    <button
                      type="button" className="btn btn-primary" disabled={!dirty || !valid}
                      aria-label={strings.codePrefixes.saveAria(row.label)} onClick={() => void save(row)}
                    >
                      {strings.codePrefixes.save}
                    </button>
                    <Tooltip label={strings.codePrefixes.restoreLabel}>
                      <button
                        type="button" className="btn" disabled={row.own_prefix === null}
                        aria-label={strings.codePrefixes.restoreAria(row.label)} onClick={() => void restore(row)}
                      >
                        <RotateCcw />
                      </button>
                    </Tooltip>
                  </span>
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
