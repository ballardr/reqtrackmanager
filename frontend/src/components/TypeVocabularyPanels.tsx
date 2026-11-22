/**
 * Module: components/TypeVocabularyPanels
 *
 * The two-tier "type vocabulary" admin pair shared by every module artefact
 * with a configurable type list (Pain Point types, Persona types, later
 * Stakeholder types): an organisation tier (`OrgTypeVocabularyPanel`, a base
 * list every project sees) and a project tier (`ProjectTypeVocabularyPanel`,
 * rename/reorder/disable of org types plus project-only additions).
 * Extracted from the previously Pain-Point-specific panels so a second typed
 * artefact doesn't add a second hand-built copy (docs/ux-style-guide.md's
 * one-component-per-pattern rule); a module's panel is now a thin wrapper
 * supplying its noun, description and API adapter.
 *
 * Both reuse `DefinitionList` for rename/add/delete and `ToggleSwitch` (via
 * `renderExtra`) for the active/enabled flag. Delete never offers
 * `DefinitionList`'s reassign-on-409 flow: these backends block deletion of a
 * type still in use outright (one org type can be referenced by many
 * projects, so there is no single reassignment target), so a 409 is
 * re-thrown as a plain `Error` telling the admin to disable the type.
 *
 * The project tier's reorder is client-side: its API only sets a row's
 * `display_order`, so `onMove` swaps the two neighbours' values via two
 * override calls. Delete on a row backed by an organisation default hides it
 * in this project (Tier-1 confirm, the project's own override row is kept so
 * existing records are unaffected); "Add organisation defaults"
 * (`RestoreOrgDefaultsButton`) shows them again. Delete on a project-only type
 * deletes it, blocked while in use.
 *
 * A module whose types carry an explanation (`withDefinition`, Pain Points) gets a second, growing text field per row; its
 * value travels with the name, but is sent only when it changed, so renaming an organisation type in a project does not
 * silently copy the organisation's definition into that project as an override. A blank value clears.
 *
 * Gating is server-side (403 surfaces through `DefinitionList`'s error
 * handling), so both panels render their controls unconditionally. The `api`
 * adapter must be a stable reference (a module-level constant), since a change
 * of identity refetches.
 */
import { type ReactNode, useEffect, useState } from "react";

import { blockedError } from "../utils/blockedError";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { DefinitionList, type DefinitionListField } from "./DefinitionList";
import { RestoreOrgDefaultsButton, type HiddenDefinition } from "./RestoreOrgDefaultsButton";
import { Spinner } from "./Spinner";
import { ToggleSwitch } from "./ToggleSwitch";

/** One organisation-level type row. */
export interface OrgTypeRow {
  id: string;
  name: string;
  is_active: boolean;
  definition?: string | null;
  /** A link pattern with one `{key}` (an external system). */
  url_template?: string | null;
}

/** One row of a project's effective type list. */
export interface EffectiveTypeRow {
  id: string;
  name: string;
  display_order: number;
  is_enabled: boolean;
  source: "org" | "project_override" | "project_local";
  /** The text shown for the type: the project's own, else the organisation's. */
  definition?: string | null;
  /** The link pattern in effect here (an external system): the project's own, else the organisation's. */
  url_template?: string | null;
}

/** The org-tier calls a module supplies. `scopeId` is the organisation id. */
export interface OrgTypeVocabularyApi<T extends OrgTypeRow> {
  list(orgId: string): Promise<T[]>;
  create(orgId: string, name: string, text?: string): Promise<unknown>;
  move(orgId: string, typeId: string, direction: "up" | "down"): Promise<unknown>;
  update(orgId: string, typeId: string, values: { name?: string; is_active?: boolean; definition?: string; url_template?: string | null }): Promise<unknown>;
  delete(orgId: string, typeId: string): Promise<unknown>;
}

/** The project-tier calls a module supplies. */
export interface ProjectTypeVocabularyApi {
  list(projectId: string): Promise<EffectiveTypeRow[]>;
  createLocal(projectId: string, name: string, displayOrder?: number, text?: string): Promise<unknown>;
  override(
    projectId: string,
    typeRefId: string,
    values: {
      name?: string | null; display_order?: number | null; is_enabled?: boolean | null; definition?: string | null;
      url_template?: string | null;
    },
  ): Promise<unknown>;
  /** Deletes a project-only type, or hides an organisation default (any org-backed row's id). */
  delete(projectId: string, typeRefId: string): Promise<unknown>;
  listHidden(projectId: string): Promise<HiddenDefinition[]>;
  /** Shows hidden organisation defaults again: the given ids, or all when omitted. */
  restore(projectId: string, orgTypeIds?: string[]): Promise<unknown>;
}

/** A second text field a vocabulary's rows carry beside the name: a type's definition, or an external system's link pattern. */
export interface VocabularyTextField {
  key: "definition" | "url_template";
  label: string;
  placeholder: string;
  ariaLabel: string;
  multiline?: boolean;
}

/** The growing "Definition" field a vocabulary opts into with `withDefinition`. */
function definitionTextField(noun: string, scope: string): VocabularyTextField {
  return {
    key: "definition",
    label: "Definition (what belongs under it)",
    placeholder: `${scope}${noun} type definition (what belongs under it)`,
    ariaLabel: `${scope}${noun} type definition`,
    multiline: true,
  };
}

/** The `DefinitionList` column for a `VocabularyTextField`. */
function textFieldColumn<T extends { definition?: string | null; url_template?: string | null }>(field: VocabularyTextField): DefinitionListField<T> {
  return {
    key: field.key,
    getValue: (item) => item[field.key] ?? "",
    label: field.label,
    placeholder: field.placeholder,
    ariaLabel: field.ariaLabel,
    track: field.multiline ? "minmax(14rem, 2.5fr)" : "minmax(14rem, 2fr)",
    multiline: field.multiline,
    optional: true,
  };
}

const SOURCE_LABEL: Record<EffectiveTypeRow["source"], string> = {
  org: "Org default",
  project_override: "Org default (overridden)",
  project_local: "Project only",
};

/** True for a row backed by an organisation default (shown as-is or overridden here), whose delete only hides it. */
function isOrgBacked(item: EffectiveTypeRow | undefined): boolean {
  return item !== undefined && item.source !== "project_local";
}

export function OrgTypeVocabularyPanel<T extends OrgTypeRow>({
  orgId,
  noun,
  description,
  api,
  withDefinition = false,
  textField,
  inUseMessage = "This type is still used by at least one project. Disable it instead of deleting it.",
}: {
  orgId: string;
  /** Singular artefact name used in labels and toasts, e.g. "Pain Point". */
  noun: string;
  /** A sentence above the list; omit when the page explains the list in its section help. */
  description?: ReactNode;
  api: OrgTypeVocabularyApi<T>;
  /** Each type also has an optional definition. */
  withDefinition?: boolean;
  /** Each type also has this other optional text field (an external system's link pattern); wins over `withDefinition`. */
  textField?: VocabularyTextField;
  inUseMessage?: string;
}) {
  const extra = textField ?? (withDefinition ? definitionTextField(noun, "") : undefined);
  const { showToast } = useToast();
  const [items, setItems] = useState<T[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [refreshKey, setRefreshKey] = useState(0);
  const reload = () => setRefreshKey((k) => k + 1);

  useEffect(() => {
    let active = true;
    api
      .list(orgId)
      .then((list) => {
        if (!active) return;
        setItems(list);
        setLoadError(null);
      })
      .catch((err) => {
        if (active) setLoadError(toErrorMessage(err, `Could not load ${noun} types.`));
      });
    return () => {
      active = false;
    };
  }, [api, noun, orgId, refreshKey]);

  if (loadError) return <div style={{ color: "var(--color-danger)" }}>{loadError}</div>;
  if (items === null) return <Spinner />;

  return (
    <div className="stack">
      {description && <p className="text-muted">{description}</p>}
      <DefinitionList<T>
        layout="grid"
        items={items}
        fields={[
          { key: "name", getValue: (item) => item.name, label: "Name", placeholder: `${noun} type name`, ariaLabel: `${noun} type name`, track: "minmax(10rem, 1fr)" },
          ...(extra ? [textFieldColumn<T>(extra)] : []),
        ]}
        getReassignLabel={(item) => item.name}
        onMove={async (id, direction) => {
          await api.move(orgId, id, direction);
          reload();
        }}
        onRename={async (id, values) => {
          const current = items.find((i) => i.id === id);
          const changed = extra !== undefined && values[extra.key] !== (current?.[extra.key] ?? "");
          await api.update(orgId, id, {
            name: values.name,
            ...(changed && extra ? { [extra.key]: extra.key === "url_template" ? values[extra.key] || null : values[extra.key] } : {}),
          });
          reload();
        }}
        onAdd={async (values) => {
          await api.create(orgId, values.name, extra ? values[extra.key] || undefined : undefined);
          showToast(`${noun} type created.`);
          reload();
        }}
        onDelete={async (id) => {
          try {
            await api.delete(orgId, id);
          } catch (err) {
            throw blockedError(err, inUseMessage);
          }
          showToast(`${noun} type deleted.`);
          reload();
        }}
        deleteLabel={`Delete ${noun} type`}
        addLabel={`Add ${noun} type`}
        extraContent="controls"
        renderExtra={(item) => (
          <span key="is-active" className="row" style={{ gap: "var(--space-2)", alignItems: "center" }}>
            <span className="text-muted" style={{ fontSize: "0.8rem" }}>Active</span>
            <ToggleSwitch
              checked={item.is_active}
              label={`Active: ${item.name}`}
              onChange={async (next) => {
                try {
                  await api.update(orgId, item.id, { is_active: next });
                  reload();
                } catch (err) {
                  showToast(toErrorMessage(err, `Could not update this ${noun} type.`), "error");
                }
              }}
            />
          </span>
        )}
      />
    </div>
  );
}

export function ProjectTypeVocabularyPanel({
  projectId,
  noun,
  description,
  api,
  withDefinition = false,
  textField,
}: {
  projectId: string;
  /** Singular artefact name used in labels and toasts, e.g. "Pain Point". */
  noun: string;
  /** A sentence above the list; omit when the page explains the list in its section help. */
  description?: ReactNode;
  api: ProjectTypeVocabularyApi;
  /** Each type also has an optional definition. */
  withDefinition?: boolean;
  /** Each type also has this other optional text field (an external system's link pattern); wins over `withDefinition`. */
  textField?: VocabularyTextField;
}) {
  const extra = textField ?? (withDefinition ? definitionTextField(noun, "Project ") : undefined);
  const { showToast } = useToast();
  const [items, setItems] = useState<EffectiveTypeRow[] | null>(null);
  const [hidden, setHidden] = useState<HiddenDefinition[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [refreshKey, setRefreshKey] = useState(0);
  const reload = () => setRefreshKey((k) => k + 1);

  useEffect(() => {
    let active = true;
    Promise.all([api.list(projectId), api.listHidden(projectId)])
      .then(([list, hiddenRows]) => {
        if (!active) return;
        setItems([...list].sort((a, b) => a.display_order - b.display_order));
        setHidden(hiddenRows);
        setLoadError(null);
      })
      .catch((err) => {
        if (active) setLoadError(toErrorMessage(err, `Could not load this project's ${noun} types.`));
      });
    return () => {
      active = false;
    };
  }, [api, noun, projectId, refreshKey]);

  if (loadError) return <div style={{ color: "var(--color-danger)" }}>{loadError}</div>;
  if (items === null) return <Spinner />;

  return (
    <div className="stack">
      {description && <p className="text-muted">{description}</p>}
      <DefinitionList<EffectiveTypeRow>
        layout="grid"
        items={items}
        fields={[
          { key: "name", getValue: (item) => item.name, label: "Name", placeholder: `Project ${noun} type name`, ariaLabel: `Project ${noun} type name`, track: "minmax(10rem, 1fr)" },
          ...(extra ? [textFieldColumn<EffectiveTypeRow>(extra)] : []),
        ]}
        getReassignLabel={(item) => item.name}
        onMove={async (id, direction) => {
          const idx = items.findIndex((i) => i.id === id);
          const otherIdx = direction === "up" ? idx - 1 : idx + 1;
          if (idx === -1 || otherIdx < 0 || otherIdx >= items.length) return;
          const a = items[idx];
          const b = items[otherIdx];
          try {
            await api.override(projectId, a.id, { display_order: b.display_order });
            await api.override(projectId, b.id, { display_order: a.display_order });
            reload();
          } catch (err) {
            showToast(toErrorMessage(err, `Could not reorder ${noun} types.`), "error");
          }
        }}
        onRename={async (id, values) => {
          const current = items.find((i) => i.id === id);
          const changed = extra !== undefined && values[extra.key] !== (current?.[extra.key] ?? "");
          await api.override(projectId, id, {
            name: values.name,
            ...(changed && extra ? { [extra.key]: extra.key === "url_template" ? values[extra.key] || null : values[extra.key] } : {}),
          });
          reload();
        }}
        onAdd={async (values) => {
          const nextOrder = items.length === 0 ? 0 : Math.max(...items.map((i) => i.display_order)) + 1;
          await api.createLocal(projectId, values.name, nextOrder, extra ? values[extra.key] || undefined : undefined);
          showToast(`Project ${noun} type created.`);
          reload();
        }}
        onDelete={async (id) => {
          const item = items.find((i) => i.id === id);
          try {
            await api.delete(projectId, id);
          } catch (err) {
            throw blockedError(err, `This type is still used by at least one ${noun} in this project. Disable it instead of deleting it.`);
          }
          showToast(isOrgBacked(item) ? `${noun} type hidden in this project.` : `Project ${noun} type deleted.`);
          reload();
        }}
        deleteLabel={`Delete ${noun} type`}
        getDeleteLabel={(item) => (isOrgBacked(item) ? `Hide ${noun} type in this project` : `Delete ${noun} type`)}
        confirmDelete={(item) =>
          isOrgBacked(item)
            ? {
                title: `Hide "${item.name}" in this project?`,
                message: `It is an organisation default. It will no longer be offered in this project, and ${noun}s that already use it keep it. Other projects are unaffected, and you can add it back with "Add organisation defaults".`,
                confirmLabel: "Hide",
              }
            : null
        }
        minItems={0}
        addLabel={`Add project-only ${noun} type`}
        extraContent="controls"
        renderExtra={(item) => (
          <span key="type-extra" className="row" style={{ gap: "var(--space-3)", alignItems: "center" }}>
            {/* A fixed width, so the toggles line up whichever label a row has. */}
            <span className="text-muted" style={{ fontSize: "0.75rem", minWidth: "10.5rem", textAlign: "right" }}>{SOURCE_LABEL[item.source]}</span>
            <span className="text-muted" style={{ fontSize: "0.8rem" }}>Enabled</span>
            <ToggleSwitch
              checked={item.is_enabled}
              label={`Enabled: ${item.name}`}
              onChange={async (next) => {
                try {
                  await api.override(projectId, item.id, { is_enabled: next });
                  reload();
                } catch (err) {
                  showToast(toErrorMessage(err, `Could not update this ${noun} type.`), "error");
                }
              }}
            />
          </span>
        )}
      />
      <div className="row">
        <RestoreOrgDefaultsButton
          hidden={hidden}
          noun={`${noun} types`}
          onRestore={async (ids) => {
            await api.restore(projectId, ids);
            showToast(ids.length === 1 ? "Organisation default added back." : `${ids.length} organisation defaults added back.`);
            reload();
          }}
        />
      </div>
    </div>
  );
}
