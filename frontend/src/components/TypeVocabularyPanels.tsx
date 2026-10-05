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
 * override calls. A project row still showing the org default
 * (`source === "org"`) has nothing project-specific to delete, which is
 * refused locally rather than surfacing a 404.
 *
 * Gating is server-side (403 surfaces through `DefinitionList`'s error
 * handling), so both panels render their controls unconditionally. The `api`
 * adapter must be a stable reference (a module-level constant), since a change
 * of identity refetches.
 */
import { type ReactNode, useEffect, useState } from "react";

import { ApiError } from "../api/client";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { DefinitionList } from "./DefinitionList";
import { Spinner } from "./Spinner";
import { ToggleSwitch } from "./ToggleSwitch";

/** One organisation-level type row. */
export interface OrgTypeRow {
  id: string;
  name: string;
  is_active: boolean;
}

/** One row of a project's effective type list. */
export interface EffectiveTypeRow {
  id: string;
  name: string;
  display_order: number;
  is_enabled: boolean;
  source: "org" | "project_override" | "project_local";
}

/** The org-tier calls a module supplies. `scopeId` is the organisation id. */
export interface OrgTypeVocabularyApi<T extends OrgTypeRow> {
  list(orgId: string): Promise<T[]>;
  create(orgId: string, name: string): Promise<unknown>;
  move(orgId: string, typeId: string, direction: "up" | "down"): Promise<unknown>;
  update(orgId: string, typeId: string, values: { name?: string; is_active?: boolean }): Promise<unknown>;
  delete(orgId: string, typeId: string): Promise<unknown>;
}

/** The project-tier calls a module supplies. */
export interface ProjectTypeVocabularyApi {
  list(projectId: string): Promise<EffectiveTypeRow[]>;
  createLocal(projectId: string, name: string, displayOrder?: number): Promise<unknown>;
  override(
    projectId: string,
    typeRefId: string,
    values: { name?: string | null; display_order?: number | null; is_enabled?: boolean | null },
  ): Promise<unknown>;
  delete(projectId: string, typeRowId: string): Promise<unknown>;
}

const SOURCE_LABEL: Record<EffectiveTypeRow["source"], string> = {
  org: "Org default",
  project_override: "Org default (overridden)",
  project_local: "Project only",
};

/** Re-throws a 409 as a plain `Error` carrying `message`, keeping the cause
 * as a property (`{ cause }` predates this project's `lib` target). */
function blockedError(err: unknown, message: string): unknown {
  if (err instanceof ApiError && err.status === 409) {
    const wrapped = new Error(message) as Error & { cause?: unknown };
    wrapped.cause = err;
    return wrapped;
  }
  return err;
}

export function OrgTypeVocabularyPanel<T extends OrgTypeRow>({
  orgId,
  noun,
  description,
  api,
  inUseMessage = "This type is still used by at least one project. Disable it instead of deleting it.",
}: {
  orgId: string;
  /** Singular artefact name used in labels and toasts, e.g. "Pain Point". */
  noun: string;
  description: ReactNode;
  api: OrgTypeVocabularyApi<T>;
  inUseMessage?: string;
}) {
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
      <p className="text-muted">{description}</p>
      <DefinitionList<T>
        items={items}
        fields={[{ key: "name", getValue: (item) => item.name, placeholder: `${noun} type name`, ariaLabel: `${noun} type name` }]}
        getReassignLabel={(item) => item.name}
        onMove={async (id, direction) => {
          await api.move(orgId, id, direction);
          reload();
        }}
        onRename={async (id, values) => {
          await api.update(orgId, id, { name: values.name });
          reload();
        }}
        onAdd={async (values) => {
          await api.create(orgId, values.name);
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
        renderExtra={(item) => (
          <span key="is-active" className="row" style={{ gap: "0.35rem", alignItems: "center" }}>
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
}: {
  projectId: string;
  /** Singular artefact name used in labels and toasts, e.g. "Pain Point". */
  noun: string;
  description: ReactNode;
  api: ProjectTypeVocabularyApi;
}) {
  const { showToast } = useToast();
  const [items, setItems] = useState<EffectiveTypeRow[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [refreshKey, setRefreshKey] = useState(0);
  const reload = () => setRefreshKey((k) => k + 1);

  useEffect(() => {
    let active = true;
    api
      .list(projectId)
      .then((list) => {
        if (!active) return;
        setItems([...list].sort((a, b) => a.display_order - b.display_order));
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
      <p className="text-muted">{description}</p>
      <DefinitionList<EffectiveTypeRow>
        items={items}
        fields={[{ key: "name", getValue: (item) => item.name, placeholder: `Project ${noun} type name`, ariaLabel: `Project ${noun} type name` }]}
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
          await api.override(projectId, id, { name: values.name });
          reload();
        }}
        onAdd={async (values) => {
          const nextOrder = items.length === 0 ? 0 : Math.max(...items.map((i) => i.display_order)) + 1;
          await api.createLocal(projectId, values.name, nextOrder);
          showToast(`Project ${noun} type created.`);
          reload();
        }}
        onDelete={async (id) => {
          const item = items.find((i) => i.id === id);
          if (item?.source === "org") {
            throw new Error("This is an organisation default with no project-specific override yet — there is nothing to delete. Disable it instead.");
          }
          try {
            await api.delete(projectId, id);
          } catch (err) {
            throw blockedError(err, `This type is still used by at least one ${noun} in this project. Disable it instead of deleting it.`);
          }
          showToast(`Project ${noun} type deleted.`);
          reload();
        }}
        deleteLabel={`Delete ${noun} type`}
        addLabel={`Add project-only ${noun} type`}
        renderExtra={(item) => (
          <span key="type-extra" className="row" style={{ gap: "0.5rem", alignItems: "center" }}>
            <span className="text-muted" style={{ fontSize: "0.75rem" }}>{SOURCE_LABEL[item.source]}</span>
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
    </div>
  );
}
