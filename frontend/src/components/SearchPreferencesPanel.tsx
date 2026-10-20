/**
 * Module: components/SearchPreferencesPanel
 *
 * The Search section of Preferences: which fields the header search and a new search look in. Stored as
 * the viewer's `search_default_fields` preference; ID and Title are always included, and any one search
 * can still pick other fields from the search page (that choice does not change this default). Comments
 * are heavier to search, so they are offered per search only and never listed here. It also holds the
 * choice of whether a project search covers organisation records (on by default).
 *
 * The saved list is validated by the server against the fields the viewer can currently choose; a key
 * that has since stopped being offered (a module switched off) is shown as "no longer available" so it
 * can be removed rather than silently ignored.
 */
import { useEffect, useId, useState } from "react";

import { ApiError, api } from "../api/client";
import {
  searchApi, SEARCH_BUILT_IN_FIELDS, SEARCH_DEFAULT_FIELDS_PREFERENCE, SEARCH_INCLUDE_ORG_RECORDS_PREFERENCE, type SearchApi,
  type SearchField,
} from "../api/search";
import { useAuth } from "../context/AuthContext";
import { useStrings } from "../context/TerminologyContext";
import { useToast } from "../context/ToastContext";
import { CheckboxField } from "./FormFields";
import { FieldShell } from "./FieldHelp";
import { SearchFieldPicker } from "./SearchFieldPicker";

/**
 * @param searchCalls Injectable search calls (stories pass a fake).
 */
export function SearchPreferencesPanel({ searchCalls = searchApi }: { searchCalls?: SearchApi }) {
  const strings = useStrings();
  const { user, refreshUser } = useAuth();
  const { showToast } = useToast();
  const controlId = useId();
  const stored = user?.ui_preferences[SEARCH_DEFAULT_FIELDS_PREFERENCE];
  const saved = Array.isArray(stored) ? (stored as string[]) : SEARCH_BUILT_IN_FIELDS;
  const [fields, setFields] = useState<SearchField[]>([]);
  const [draft, setDraft] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const current = draft ?? saved;
  const dirty = draft !== null && JSON.stringify(draft) !== JSON.stringify(saved);

  useEffect(() => {
    let active = true;
    searchCalls.fields().then((found) => active && setFields(found.filter((f) => f.default_allowed !== false))).catch(() => undefined);
    return () => {
      active = false;
    };
  }, [searchCalls]);

  const includeOrgRecords = user?.ui_preferences[SEARCH_INCLUDE_ORG_RECORDS_PREFERENCE] !== false;

  async function saveIncludeOrgRecords(next: boolean) {
    setError(null);
    try {
      await api.patch("/api/v1/auth/me/preferences", { ui_preferences: { [SEARCH_INCLUDE_ORG_RECORDS_PREFERENCE]: next } });
      await refreshUser();
      showToast(strings.preferences.saved);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : strings.common.error);
    }
  }

  async function save(next: string[] | null) {
    setError(null);
    try {
      await api.patch("/api/v1/auth/me/preferences", { ui_preferences: { [SEARCH_DEFAULT_FIELDS_PREFERENCE]: next } });
      await refreshUser();
      setDraft(null);
      showToast(strings.preferences.saved);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : strings.common.error);
    }
  }

  return (
    <div className="card stack">
      <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.preferences.searchGroup}</h2>
      <FieldShell
        label={strings.search.fieldsLabel}
        controlId={controlId}
        help={strings.help.searchDefaultFields}
        hint={strings.preferences.searchFieldsHint}
      >
        <SearchFieldPicker id={controlId} label={strings.search.fieldsLabel} fields={fields} value={current} onChange={setDraft} />
      </FieldShell>
      <CheckboxField
        help={strings.help.searchIncludeOrgRecords}
        label={strings.preferences.searchIncludeOrgRecords}
        checked={includeOrgRecords}
        onChange={saveIncludeOrgRecords}
      />
      {error && <div style={{ color: "var(--color-danger)" }} role="alert">{error}</div>}
      <div className="row">
        <button type="button" className="btn btn-primary" disabled={!dirty} onClick={() => save(draft)}>
          {strings.preferences.save}
        </button>
        <button type="button" className="btn" disabled={stored === undefined && draft === null} onClick={() => save(null)}>
          {strings.preferences.searchResetDefault}
        </button>
      </div>
    </div>
  );
}
