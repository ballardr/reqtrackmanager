/**
 * Module: components/RecordCodePrefixPanel
 *
 * Administration of the prefix new records are numbered with, for one tier: Organisation Admin (the default every
 * {project} of the organisation starts from) and Project Admin (the {project}'s own prefixes, with the value
 * inherited from a parent {project} or the organisation as the placeholder). Record types sit in one foldable
 * section for Core and one for each module; each row has the type's name, a prefix input, where the inherited value
 * comes from, and the controls that save it or return to the inherited value.
 *
 * - Sections come from the API (`module_key` and `module_name`, from the module registry), never a module list in
 *   this file, so a module's types appear under its own heading with no edit here.
 * - One compact grid with fixed column widths and a single heading row, so rows line up across sections. A folded
 *   section shows how many prefixes this tier set itself (a pill and an accent border).
 * - One request per row: a prefix is checked against the other types' prefixes in the same scope, so a swap of two
 *   prefixes is two deliberate ordered changes, not a batch.
 * - The server owns every rule (shape, uniqueness, nesting); the input blocks only what can never be valid (not two
 *   to five letters) and shows the server's message on a refusal. A change affects records created afterwards only;
 *   the column help says so.
 *
 * Dependencies: `GET/PUT/DELETE /api/v1/orgs/{id}/code-prefixes` and `/api/v1/projects/{id}/code-prefixes`.
 */
import { RotateCcw } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { api } from "../api/client";
import type { CodePrefixRow } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage } from "../context/ToastContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { useMutation } from "../hooks/useMutation";
import { CollapsibleSection } from "./CollapsibleSection";
import { FieldHelp } from "./FieldHelp";
import { InlineTextInput } from "./FormFields";
import { Spinner } from "./Spinner";
import { Tooltip } from "./Tooltip";

/** Where the panel reads and writes: an organisation's defaults, or one project's own prefixes. */
export type CodePrefixScope = { kind: "organization"; organizationId: string } | { kind: "project"; projectId: string };

/** The longest prefix the server accepts. */
const MAX_PREFIX_LENGTH = 5;
const PREFIX_SHAPE = /^[A-Z]{2,5}$/;

/** Fixed column tracks shared by the heading row and every section (an auto track would size each grid to its own
 *  content, so the heading and the rows would not line up) and compact. */
const GRID_TRACKS = "14rem 7rem 8rem";
/** The project tier adds a column saying which tier its inherited prefix comes from; an organisation has none. */
const GRID_TRACKS_WITH_SOURCE = "14rem 7rem 11rem 8rem";

/** One section of the panel: the Core types, or one module's. */
interface PrefixSection {
  key: string;
  title: string;
  rows: CodePrefixRow[];
}

/** Groups the rows into sections in the order the API sent them (Core first, then each module by name). */
function groupRows(rows: CodePrefixRow[], coreTitle: string): PrefixSection[] {
  const sections: PrefixSection[] = [];
  for (const row of rows) {
    const key = row.module_key ?? "core";
    let section = sections.find((s) => s.key === key);
    if (!section) {
      section = { key, title: row.module_name ?? coreTitle, rows: [] };
      sections.push(section);
    }
    section.rows.push(row);
  }
  return sections;
}

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

  const tracks = scope.kind === "project" ? GRID_TRACKS_WITH_SOURCE : GRID_TRACKS;
  const sections = useMemo(() => groupRows(rows ?? [], strings.codePrefixes.core), [rows, strings.codePrefixes.core]);

  if (loadError) return <div style={{ color: "var(--color-danger)" }}>{loadError}</div>;
  if (!rows) return <Spinner />;
  if (rows.length === 0) return <p className="text-muted" style={{ margin: 0 }}>{strings.codePrefixes.empty}</p>;

  function renderRow(row: CodePrefixRow) {
    const value = draft[row.artefact_type] ?? row.own_prefix ?? "";
    const dirty = draft[row.artefact_type] !== undefined && draft[row.artefact_type] !== (row.own_prefix ?? "");
    const valid = PREFIX_SHAPE.test(value);
    const inheritedNote = row.own_prefix === null && !value
      ? row.inherited_source === "parent_project" ? strings.codePrefixes.fromParent
        : row.inherited_source === "organization" ? strings.codePrefixes.fromOrganisation : null
      : null;
    return (
      <div key={row.artefact_type} className="definition-grid__row" data-artefact-type={row.artefact_type}>
        <div className="definition-grid__cell">{row.label}</div>
        <div className="definition-grid__cell">
          <InlineTextInput
            ariaLabel={strings.codePrefixes.prefixOf(row.label)} value={value} placeholder={row.inherited_prefix}
            disabled={!canEdit}
            onChange={(next) => setDraft((d) => ({ ...d, [row.artefact_type]: next.toUpperCase().slice(0, MAX_PREFIX_LENGTH) }))}
          />
        </div>
        {scope.kind === "project" && <div className="definition-grid__cell text-muted">{inheritedNote}</div>}
        <div className="definition-grid__actions">
          {canEdit && (
            <>
              <button
                type="button" className="btn" disabled={!dirty || !valid}
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
            </>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="stack" style={{ gap: "var(--space-2)" }}>
      <div className="definition-grid" style={{ gridTemplateColumns: tracks, justifyContent: "start" }}>
        <div className="definition-grid__head">{strings.codePrefixes.recordType}</div>
        <div className="definition-grid__head">
          <span className="field-caption">
            <span>{strings.codePrefixes.prefix}</span>
            <FieldHelp label={strings.codePrefixes.prefix} help={strings.help.recordCodePrefix} />
          </span>
        </div>
        {scope.kind === "project" && <div className="definition-grid__head">{strings.codePrefixes.inheritedFrom}</div>}
        <div className="definition-grid__head" />
      </div>
      {sections.map((section) => {
        const custom = section.rows.filter((r) => r.own_prefix !== null).length;
        return (
          <CollapsibleSection
            key={section.key} sectionKey={`codePrefixes.${scope.kind}.${section.key}`} title={section.title} variant="plain"
            defaultCollapsed={section.key !== "core"} marked={custom > 0}
            summary={custom > 0 ? strings.codePrefixes.customCount(custom) : strings.codePrefixes.typeCount(section.rows.length)}
          >
            <div
              className="definition-grid" role="group" aria-label={section.title}
              style={{ gridTemplateColumns: tracks, justifyContent: "start" }}
            >
              {section.rows.map(renderRow)}
            </div>
          </CollapsibleSection>
        );
      })}
    </div>
  );
}
