/**
 * Module: components/NavLabelsPanel
 *
 * Administration of navigation names for one tier, shared by Project Admin (the project's own names, with the
 * name inherited from a parent project or the organisation shown as the placeholder) and Organisation Admin
 * (the default every project of the organisation starts from). Each row is one entry of the project
 * navigation: its built-in name, an input for the name to show instead, and a restore control. A name change
 * covers the navigation entry, the page title and the back link of that entry's records; record nouns keep
 * the terminology setting.
 *
 * Design decisions:
 * - Edits are a draft saved together with one button (one request replaces the whole set), so the panel shows
 *   what a save will do; "Restore" clears a row's draft and takes effect on save.
 * - A core entry's built-in name comes from the string table (so it follows the project's terminology); a
 *   module entry's from the server's catalogue.
 * - After a project save the navigation refreshes at once (`refreshNavLabels`).
 */
import { RotateCcw } from "lucide-react";
import { useCallback, useState } from "react";

import { api } from "../api/client";
import type { NavLabelItem, NavLabels } from "../api/types";
import { refreshNavLabels } from "../context/NavLabelValue";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage } from "../context/ToastContext";
import type { Strings } from "../i18n/strings";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { useMutation } from "../hooks/useMutation";
import { FieldHelp } from "./FieldHelp";
import { InlineTextInput } from "./FormFields";

/** Where the panel reads and writes: an organisation's defaults, or one project's own names. */
export type NavLabelScope = { kind: "organisation"; organizationId: string } | { kind: "project"; projectId: string };

/** The longest name the server accepts. */
const MAX_NAME_LENGTH = 40;

function basePath(scope: NavLabelScope): string {
  return scope.kind === "organisation" ? `/api/v1/orgs/${scope.organizationId}/nav-labels` : `/api/v1/projects/${scope.projectId}/nav-labels`;
}

/** The built-in name of a core entry, resolved through the project's terminology; undefined for a module entry. */
function coreLabel(key: string, strings: Strings): string | undefined {
  const labels: Record<string, string> = {
    overview: strings.nav.overview,
    requirements: strings.nav.requirements,
    "change-requests": strings.nav.changeRequests,
    actions: strings.nav.actions,
    files: strings.files.title,
    "reviews-due": strings.reviews.projectTitle,
    history: strings.history.title,
    admin: strings.nav.admin,
  };
  return labels[key];
}

/**
 * @param scope The tier to administer.
 */
export function NavLabelsPanel({ scope }: { scope: NavLabelScope }) {
  const strings = useStrings();
  const run = useMutation();
  const [items, setItems] = useState<NavLabelItem[] | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [loadError, setLoadError] = useState<string | null>(null);
  const path = basePath(scope);

  const reload = useCallback(async () => {
    try {
      const body = await api.get<NavLabels>(path);
      setItems(body.items);
      setDraft(Object.fromEntries(body.items.filter((i) => i.own).map((i) => [i.key, i.own as string])));
      setLoadError(null);
    } catch (err) {
      setLoadError(toErrorMessage(err, strings.navLabels.loadFailed));
    }
  }, [path, strings.navLabels.loadFailed]);

  useLoadOnChange(reload, [path]);

  async function save() {
    const names = Object.fromEntries(Object.entries(draft).filter(([, value]) => value.trim() !== ""));
    if (await run(() => api.put(path, { names }), "save", strings.navLabels.noun)) {
      if (scope.kind === "project") refreshNavLabels(scope.projectId);
      await reload();
    }
  }

  if (loadError) return <div style={{ color: "var(--color-danger)" }}>{loadError}</div>;
  if (!items) return null;
  const saved = Object.fromEntries(items.filter((i) => i.own).map((i) => [i.key, i.own as string]));
  const current = Object.fromEntries(Object.entries(draft).filter(([, value]) => value.trim() !== "").map(([k, v]) => [k, v.trim()]));
  const dirty = JSON.stringify(Object.entries(current).sort()) !== JSON.stringify(Object.entries(saved).sort());
  return (
    <div className="stack">
      <table className="table" aria-label={strings.navLabels.heading}>
        <thead>
          <tr>
            <th>{strings.navLabels.entry}</th>
            <th>
              <span className="field-caption">
                <span>{strings.navLabels.name}</span>
                <FieldHelp label={strings.navLabels.name} help={strings.help.navLabelName} />
              </span>
            </th>
            <th />
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const builtIn = coreLabel(item.key, strings) ?? item.label;
            const placeholder = item.inherited ?? builtIn;
            const value = draft[item.key] ?? "";
            return (
              <tr key={item.key} data-nav-key={item.key}>
                <td>{builtIn}</td>
                <td>
                  <InlineTextInput
                    ariaLabel={strings.navLabels.nameOf(builtIn)} value={value} placeholder={placeholder} maxWidth={320}
                    onChange={(next) => setDraft((d) => ({ ...d, [item.key]: next.slice(0, MAX_NAME_LENGTH) }))}
                  />
                  {!value && item.inherited && (
                    <span className="text-muted" style={{ marginLeft: "var(--space-2)" }}>
                      {item.inherited_from === "ancestor" ? strings.navLabels.fromParent : strings.navLabels.fromOrganisation}
                    </span>
                  )}
                </td>
                <td>
                  <button
                    className="btn" type="button" disabled={!value}
                    aria-label={strings.navLabels.restoreAria(builtIn)} title={strings.navLabels.restoreAria(builtIn)}
                    onClick={() => setDraft((d) => Object.fromEntries(Object.entries(d).filter(([key]) => key !== item.key)))}
                  >
                    <RotateCcw />
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <button className="btn btn-primary" type="button" disabled={!dirty} onClick={() => void save()} style={{ alignSelf: "flex-start" }}>
        {strings.navLabels.save}
      </button>
    </div>
  );
}
