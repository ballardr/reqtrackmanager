/**
 * Module: components/ModuleSettingsList
 *
 * The shared "Modules" settings list used by Org Admin and Project Admin:
 * one row per module (name, version, a two-line-clamped description with
 * "More", an optional hint, and one caller-supplied control), with any
 * sub-components collapsed behind a one-line summary disclosure.
 *
 * Design decisions:
 * - A list, not a table: each row labels itself, so there are no column
 *   headers (the old table's three-line "Default for new projects" header
 *   was most of its height).
 * - Controls are render-slots (`control`), so the org page can pass a
 *   three-state availability `<select>` and the project page an on/off
 *   `ToggleSwitch` without this component knowing either's semantics.
 * - `ModuleAvailabilitySelect` is one three-state control instead of two
 *   toggles (hard on/off + default for new projects): the default does
 *   nothing while the module is off, so only three states are real.
 * - Sub-components start collapsed — most admins never change them, and
 *   expanding them all by default is what made the old page read as a
 *   wall of toggles.
 */
import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { MODULE_AVAILABILITY_LABEL, type ModuleAvailability } from "../api/types";
import { t } from "../i18n/strings";

const strings = t();

/** One sub-component row: a name and its control. */
export interface ModuleSettingsSubItem {
  key: string;
  name: string;
  control: ReactNode;
}

/** One module row. `muted` greys the row (e.g. not on the org's plan). */
export interface ModuleSettingsItem {
  key: string;
  name: string;
  version?: string;
  description?: string;
  hint?: string | null;
  muted?: boolean;
  control: ReactNode;
  subItems?: ModuleSettingsSubItem[];
  /** Collapsed disclosure text, e.g. "5 components · all on". */
  subSummary?: string;
}

/**
 * Renders the module settings list.
 *
 * Args:
 *   items: The module rows, in display order.
 */
export function ModuleSettingsList({ items }: { items: ModuleSettingsItem[] }) {
  return (
    <ul className="module-settings-list">
      {items.map((item) => (
        <ModuleSettingsRow key={item.key} item={item} />
      ))}
    </ul>
  );
}

/** One module row plus its collapsible sub-component list. */
function ModuleSettingsRow({ item }: { item: ModuleSettingsItem }) {
  const [subOpen, setSubOpen] = useState(false);
  const subListId = `module-settings-sub-${item.key}`;
  return (
    <li className="module-settings-row" style={item.muted ? { opacity: 0.55 } : undefined}>
      <div className="module-settings-main">
        <div className="module-settings-text">
          <div>
            <strong>{item.name}</strong>
            {item.version && <span className="text-muted module-settings-version">v{item.version}</span>}
          </div>
          {item.description && <ClampedDescription text={item.description} />}
          {item.hint && <span className="text-muted module-settings-small">{item.hint}</span>}
        </div>
        <div className="module-settings-control">{item.control}</div>
      </div>
      {item.subItems && item.subItems.length > 0 && (
        <>
          <button
            type="button"
            className="disclosure-toggle module-settings-small"
            aria-expanded={subOpen}
            aria-controls={subListId}
            onClick={() => setSubOpen((open) => !open)}
          >
            {subOpen ? <ChevronDown size={14} aria-hidden /> : <ChevronRight size={14} aria-hidden />}
            {item.subSummary ?? strings.common.moduleComponentsSummary(item.subItems.length)}
          </button>
          {subOpen && (
            <ul id={subListId} className="module-settings-sublist">
              {item.subItems.map((sub) => (
                <li key={sub.key} className="module-settings-main">
                  <span>{sub.name}</span>
                  <div className="module-settings-control">{sub.control}</div>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </li>
  );
}

/** A description clamped to two lines, with a "More"/"Less" toggle shown
 * only when the text actually overflows. */
function ClampedDescription({ text }: { text: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [overflows, setOverflows] = useState(false);
  useLayoutEffect(() => {
    const el = ref.current;
    if (el && !expanded) setOverflows(el.scrollHeight > el.clientHeight + 1);
  }, [text, expanded]);
  return (
    <span className="text-muted module-settings-small">
      <span ref={ref} className={expanded ? undefined : "line-clamp-2"}>
        {text}
      </span>
      {(overflows || expanded) && (
        <button type="button" className="text-button" onClick={() => setExpanded((e) => !e)}>
          {expanded ? strings.common.showLess : strings.common.showMore}
        </button>
      )}
    </span>
  );
}

const AVAILABILITY_OPTIONS: ModuleAvailability[] = ["off", "opt_in", "default_on"];

/**
 * The org-level three-state availability `<select>` (Off / Available, off
 * for new projects / On for new projects), labelled via
 * `MODULE_AVAILABILITY_LABEL`.
 *
 * Args:
 *   value: The current availability.
 *   onChange: Called with the newly chosen availability.
 *   label: Accessible name (e.g. "Compliance availability").
 *   disabled: Greys the control out (e.g. not on the org's plan).
 */
export function ModuleAvailabilitySelect({
  value,
  onChange,
  label,
  disabled,
}: {
  value: ModuleAvailability;
  onChange: (next: ModuleAvailability) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <select
      className="input"
      aria-label={label}
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value as ModuleAvailability)}
    >
      {AVAILABILITY_OPTIONS.map((option) => (
        <option key={option} value={option}>
          {MODULE_AVAILABILITY_LABEL[option]}
        </option>
      ))}
    </select>
  );
}
