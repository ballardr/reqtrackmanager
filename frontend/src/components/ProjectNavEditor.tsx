/**
 * Module: components/ProjectNavEditor
 *
 * The "Customise navigation" modal for the Project nav section
 * (docs/plans/platform-enhancements-2026-10-plan.md Phase 4): reorder items, move them behind
 * "More", and choose whether the layout applies to every project or just this one.
 *
 * Responsibilities:
 * - Edit a draft of the layout in effect; nothing is persisted until Save.
 * - Write the result to the user's default (`project_nav`) or this project's override
 *   (`project_nav:<id>`) in one `ui_preferences` PATCH, with a toast.
 * - Prune overrides left behind for projects the user can no longer reach, so the bounded
 *   `ui_preferences` bag does not fill with dead keys.
 *
 * Design decisions:
 * - Up/down buttons are the reorder control: keyboard- and screen-reader-accessible, which a
 *   drag-only list is not.
 * - Pinned items (Overview, Admin) have no "move to More" control — see `PINNED_NAV_KEYS`.
 * - Saving for all projects while this project has its own override also removes that
 *   override (the user edited what they see here, so leaving it shadowing the save would look
 *   like the save did nothing); the form says so.
 *
 * Dependencies: `AuthContext` (preference writes), `ToastContext`, the projects list endpoint
 * (pruning only; failure skips pruning).
 */
import { ArrowDown, ArrowUp, ChevronsDown, ChevronsUp } from "lucide-react";
import { useState } from "react";

import { api } from "../api/client";
import type { ProjectListItem, UiPreferenceValue } from "../api/types";
import { useAuth } from "../context/AuthContext";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import {
  arrangeProjectNav,
  navPrefFromArrangement,
  parseNavPref,
  PINNED_NAV_KEYS,
  PROJECT_NAV_OVERRIDE_PREFIX,
  PROJECT_NAV_PREF_KEY,
  projectNavOverrideKey,
  resolveNavPref,
  type ProjectNavItem,
} from "../navigation/projectNav";
import { Modal } from "./Modal";

type Scope = "all" | "project";

/** Moves `key` one step within `list` (clamped); returns a new list. */
function moveWithin(list: string[], key: string, delta: -1 | 1): string[] {
  const from = list.indexOf(key);
  const to = from + delta;
  if (from === -1 || to < 0 || to >= list.length) return list;
  const next = [...list];
  next.splice(from, 1);
  next.splice(to, 0, key);
  return next;
}

/** Ids of every project (active and archived) the caller can still reach, or `null` if unknown. */
async function fetchReachableProjectIds(): Promise<Set<string> | null> {
  try {
    const [active, archived] = await Promise.all([
      api.get<ProjectListItem[]>("/api/v1/projects?archived=false"),
      api.get<ProjectListItem[]>("/api/v1/projects?archived=true"),
    ]);
    return new Set([...active, ...archived].map((project) => project.id));
  } catch {
    return null;
  }
}

/**
 * Modal editor for the Project nav layout.
 *
 * Args:
 *   projectId: The project whose nav is being edited (scopes the override).
 *   items: Every available item in product-default order.
 *   onClose: Called after Save, Remove, or Cancel.
 */
export function ProjectNavEditor({
  projectId, items, onClose,
}: { projectId: string; items: ProjectNavItem[]; onClose: () => void }) {
  const strings = useStrings();
  const customise = strings.nav.customise;
  const { user, setUiPreferences } = useAuth();
  const { showToast } = useToast();
  const prefs = user?.ui_preferences ?? {};
  const overrideKey = projectNavOverrideKey(projectId);
  const hasOverride = parseNavPref(prefs[overrideKey]) !== null;

  const [{ main, more }, setLayout] = useState(() => {
    const arranged = arrangeProjectNav(items, resolveNavPref(prefs[PROJECT_NAV_PREF_KEY], prefs[overrideKey]));
    return { main: arranged.main.map((item) => item.key), more: arranged.more.map((item) => item.key) };
  });
  const [scope, setScope] = useState<Scope>(hasOverride ? "project" : "all");
  const [saving, setSaving] = useState(false);

  const itemByKey = new Map(items.map((item) => [item.key, item]));

  function toggleSection(key: string) {
    setLayout((current) =>
      current.main.includes(key)
        ? { main: current.main.filter((k) => k !== key), more: [...current.more, key] }
        : { main: [...current.main, key], more: current.more.filter((k) => k !== key) },
    );
  }

  function move(section: "main" | "more", key: string, delta: -1 | 1) {
    setLayout((current) => ({ ...current, [section]: moveWithin(current[section], key, delta) }));
  }

  function resetToDefault() {
    setLayout({ main: items.map((item) => item.key), more: [] });
  }

  async function removeOverride() {
    try {
      await setUiPreferences({ [overrideKey]: null });
      showToast(customise.overrideRemoved);
      onClose();
    } catch (err) {
      showToast(toErrorMessage(err, customise.saveFailed), "error");
    }
  }

  async function save() {
    setSaving(true);
    try {
      const toItems = (keys: string[]) => keys.flatMap((key) => itemByKey.get(key) ?? []);
      const pref = navPrefFromArrangement(toItems(main), toItems(more));
      const patch: Record<string, UiPreferenceValue | null> = {};
      if (scope === "all") {
        patch[PROJECT_NAV_PREF_KEY] = pref;
        if (hasOverride) patch[overrideKey] = null;
      } else {
        patch[overrideKey] = pref;
      }
      const otherOverrides = Object.keys(prefs).filter((key) => key.startsWith(PROJECT_NAV_OVERRIDE_PREFIX) && key !== overrideKey);
      if (otherOverrides.length > 0) {
        const reachable = await fetchReachableProjectIds();
        if (reachable) {
          for (const key of otherOverrides) {
            if (!reachable.has(key.slice(PROJECT_NAV_OVERRIDE_PREFIX.length))) patch[key] = null;
          }
        }
      }
      await setUiPreferences(patch);
      showToast(customise.saved);
      onClose();
    } catch (err) {
      // Stay open so the draft isn't lost; the server's own message (e.g. the size bound) is shown.
      showToast(toErrorMessage(err, customise.saveFailed), "error");
      setSaving(false);
    }
  }

  function renderRow(section: "main" | "more", key: string, index: number, list: string[]) {
    const item = itemByKey.get(key);
    if (!item) return null;
    const pinned = PINNED_NAV_KEYS.includes(key);
    return (
      <li key={key} className="row" style={{ justifyContent: "space-between" }}>
        <span className="row" style={{ gap: "0.5rem" }}>{item.icon} {item.label}</span>
        <span className="row" style={{ gap: "0.25rem" }}>
          {pinned ? (
            <span className="text-muted" style={{ fontSize: "0.8rem" }}>{customise.pinned}</span>
          ) : (
            <button
              type="button" className="btn" onClick={() => toggleSection(key)}
              aria-label={section === "main" ? customise.moveToMore(item.label) : customise.moveToNavigation(item.label)}
              title={section === "main" ? customise.moveToMore(item.label) : customise.moveToNavigation(item.label)}
            >
              {section === "main" ? <ChevronsDown size={14} /> : <ChevronsUp size={14} />}
            </button>
          )}
          <button
            type="button" className="btn" onClick={() => move(section, key, -1)} disabled={index === 0}
            aria-label={customise.moveUp(item.label)} title={customise.moveUp(item.label)}
          >
            <ArrowUp size={14} />
          </button>
          <button
            type="button" className="btn" onClick={() => move(section, key, 1)} disabled={index === list.length - 1}
            aria-label={customise.moveDown(item.label)} title={customise.moveDown(item.label)}
          >
            <ArrowDown size={14} />
          </button>
        </span>
      </li>
    );
  }

  return (
    <Modal title={customise.title} onClose={onClose}>
      <p className="text-muted" style={{ margin: 0 }}>{customise.intro}</p>
      <fieldset className="stack" style={{ border: "none", padding: 0, margin: 0, gap: "0.25rem" }}>
        <legend style={{ fontWeight: 600, padding: 0 }}>{customise.scopeLegend}</legend>
        <label>
          <input type="radio" name="project-nav-scope" checked={scope === "all"} onChange={() => setScope("all")} />{" "}
          {customise.scopeAll}
        </label>
        <label>
          <input type="radio" name="project-nav-scope" checked={scope === "project"} onChange={() => setScope("project")} />{" "}
          {customise.scopeProject}
        </label>
        {scope === "all" && hasOverride && <span className="text-muted">{customise.scopeReplacesOverride}</span>}
      </fieldset>
      <section className="stack" style={{ gap: "0.4rem" }} aria-label={customise.navigationHeading}>
        <h3 style={{ margin: 0, fontSize: "0.95rem" }}>{customise.navigationHeading}</h3>
        <ul className="stack" style={{ listStyle: "none", margin: 0, padding: 0, gap: "0.3rem" }}>
          {main.map((key, index) => renderRow("main", key, index, main))}
        </ul>
      </section>
      <section className="stack" style={{ gap: "0.4rem" }} aria-label={customise.moreHeading}>
        <h3 style={{ margin: 0, fontSize: "0.95rem" }}>{customise.moreHeading}</h3>
        {more.length === 0 ? (
          <p className="text-muted" style={{ margin: 0 }}>{customise.emptyMore}</p>
        ) : (
          <ul className="stack" style={{ listStyle: "none", margin: 0, padding: 0, gap: "0.3rem" }}>
            {more.map((key, index) => renderRow("more", key, index, more))}
          </ul>
        )}
      </section>
      <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
        <span className="row">
          <button type="button" className="btn" onClick={resetToDefault}>{customise.resetToDefault}</button>
          {hasOverride && (
            <button type="button" className="btn" onClick={removeOverride}>{customise.removeOverride}</button>
          )}
        </span>
        <span className="row">
          <button type="button" className="btn" onClick={onClose}>{strings.common.cancel}</button>
          <button type="button" className="btn btn-primary" onClick={save} disabled={saving}>{customise.save}</button>
        </span>
      </div>
    </Modal>
  );
}
