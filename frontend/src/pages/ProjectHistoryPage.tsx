/**
 * Module: pages/ProjectHistoryPage
 *
 * The project's changes-over-time view (C-A-10): a `ProjectActivityTable` of Time, Type, Event, Record(s) and Person (Time and Event always; the others through the column chooser), newest first, narrowed by a filter panel
 * (period, type, change, person or group, discussion comments) and exportable as CSV, PDF, Word, ODT or ODS with the same filters.
 * Every filter and the sort live in the URL (`hooks/useUrlFilter`); pages come from `GET .../changes` (server-side narrowing and paging) with
 * the previous rows dimmed while a filter loads; the local period converts to UTC instants (`utils/historyPeriod`). A day is written once, on
 * its first row; the overview's activity widget draws the same table; Event and the Activity aside share `describeActivityAction`; the Person filter holds people and groups on parity
 * (`PrincipalListField`). Dependencies: `GET /api/v1/projects/{id}/changes` (+ `/facets`, `/actors`, `/export`).
 */
import { useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "../api/client";
import {
  ACTIVITY_KIND_LABEL, activityEntityLabel, type ActivityKind, type ChangeEntry, type Principal, type PrincipalRef,
} from "../api/types";
import { FilterCheckbox, FilterField, FilterPanel } from "../components/FilterPanel";
import { ListExportMenu } from "../components/ListExportMenu";
import { ListPageLayout } from "../components/ListPageLayout";
import { MultiSelectDropdown, type MultiSelectOption } from "../components/MultiSelectDropdown";
import { PeriodFilter } from "../components/PeriodFilter";
import { PrincipalListField } from "../components/PrincipalListField";
import { ProjectActivityTable } from "../components/ProjectActivityTable";
import { Spinner } from "../components/Spinner";
import { cycleSort } from "../components/sortState";
import { useOrgLabelCapitalized } from "../context/BrandingContext";
import { ProjectContext } from "../context/ProjectContextValue";
import { useStrings } from "../context/TerminologyContext";
import { useActivityColumnChoice } from "../hooks/useActivityColumns";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { useRestoredRowCount } from "../hooks/useListPosition";
import { useUrlChoice, useUrlFlag, useUrlList, useUrlSort, useUrlText } from "../hooks/useUrlFilter";
import { toActivityRows } from "../utils/activityRows";
import { PERIOD_KEYS, periodRange } from "../utils/historyPeriod";

const PAGE_SIZE = 30;
/** The kinds the Change filter offers: how a record or setting changed. Links, tags and access are metadata, chosen in the Type filter. */
const CHANGE_KINDS: ActivityKind[] = ["created", "edited", "status", "deleted"];
const SORT_KEYS = ["time"] as const;

/** One heading of the Type list: a module's records, or a group of metadata types. */
interface HistoryTypeGroup {
  key: string;
  label: string;
  section: "records" | "metadata";
  types: string[];
}

interface HistoryFacets {
  entity_types: string[];
  groups: HistoryTypeGroup[];
  total: number;
}

/** `type:id` of a principal, the form the API and the URL both use. */
const principalKey = (ref: PrincipalRef) => `${ref.type}:${ref.id}`;

/**
 * The Project history page.
 *
 * @returns The titled list with its filter panel, table and "Show more".
 */
export function ProjectHistoryPage() {
  const strings = useStrings();
  const { projectId } = useParams<{ projectId: string }>();
  const organizationId = useContext(ProjectContext).organizationId ?? undefined;
  const orgLabelCap = useOrgLabelCapitalized();
  const limitFor = useRestoredRowCount(PAGE_SIZE);

  const [period, setPeriod] = useUrlChoice("period", PERIOD_KEYS);
  const [since, setSince] = useUrlText("since");
  const [until, setUntil] = useUrlText("until");
  const [entityTypes, setEntityTypes] = useUrlList("type");
  const [groups, setGroups] = useUrlList("group");
  const [kinds, setKinds] = useUrlList("kind");
  const [actors, setActors] = useUrlList("actor");
  const [includeComments, setIncludeComments] = useUrlFlag("comments");
  const [sort, setSort] = useUrlSort(SORT_KEYS);

  const [entries, setEntries] = useState<ChangeEntry[] | null>(null);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [facets, setFacets] = useState<HistoryFacets | null>(null);
  const [actorLabels, setActorLabels] = useState<Record<string, Principal>>({});

  /** The filters as the query the list and the export both send (no paging). */
  const filterParams = useCallback((): URLSearchParams => {
    const params = new URLSearchParams();
    const range = periodRange(period, since, until);
    if (range.since) params.set("since", range.since);
    if (range.until) params.set("until", range.until);
    if (includeComments) params.set("include_comments", "true");
    entityTypes.forEach((type) => params.append("entity_type", type));
    groups.forEach((group) => params.append("group", group));
    kinds.forEach((kind) => params.append("kind", kind));
    actors.forEach((actor) => params.append("actor", actor));
    return params;
  }, [period, since, until, includeComments, entityTypes, groups, kinds, actors]);

  // A response is applied only if it still answers the latest filter change by the time it resolves (a date input
  // can change several times in quick succession); a "Show more" append does not bump the generation.
  const requestGeneration = useRef(0);

  async function loadChanges(offset: number, append: boolean) {
    if (!projectId) return;
    const generation = requestGeneration.current;
    const params = filterParams();
    params.set("limit", String(limitFor(offset)));
    params.set("offset", String(offset));
    if (sort?.direction === "asc") params.set("order", "oldest");
    const page = await api.getPage<ChangeEntry>(`/api/v1/projects/${projectId}/changes?${params.toString()}`);
    if (generation !== requestGeneration.current) return;
    setEntries((prev) => (append && prev ? [...prev, ...page.items] : page.items));
    setTotal(page.total);
    setLoading(false);
  }

  async function reload() {
    requestGeneration.current += 1;
    setLoading(true);
    await loadChanges(0, false).catch(() => {
      setEntries((prev) => prev ?? []);
      setLoading(false);
    });
  }

  useLoadOnChange(reload, [projectId, period, since, until, includeComments, entityTypes.join(","), groups.join(","), kinds.join(","), actors.join(","), sort?.direction]);

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    api.get<HistoryFacets>(`/api/v1/projects/${projectId}/changes/facets`).then(
      (found) => !cancelled && setFacets(found),
      () => !cancelled && setFacets(null),
    );
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  // The chips of the Person filter are named by the server, so a view restored from a link shows names.
  const actorsKey = actors.join(",");
  useEffect(() => {
    if (!projectId || !actorsKey) return;
    let cancelled = false;
    const query = new URLSearchParams();
    actorsKey.split(",").forEach((actor) => query.append("actor", actor));
    api.get<Principal[]>(`/api/v1/projects/${projectId}/changes/actors?${query.toString()}`).then(
      (found) => !cancelled && setActorLabels(Object.fromEntries(found.map((principal) => [principalKey(principal), principal]))),
      () => undefined,
    );
    return () => {
      cancelled = true;
    };
  }, [projectId, actorsKey]);

  const actorValues: Principal[] = actors.flatMap((key) => {
    const [type, id] = [key.slice(0, key.indexOf(":")), key.slice(key.indexOf(":") + 1)];
    return actorLabels[key] ?? [{ type: type as Principal["type"], id, label: "…", member_count: null, exists: true }];
  });

  /**
   * The two-level Type list: a section caption, then each group's heading (choosing it chooses all its types)
   * and its types. A type of a chosen group shows ticked and cannot be unticked on its own; a type or group in
   * the URL that the facets do not list (an old link) is still shown so it can be removed.
   */
  const typeOptions = useMemo((): MultiSelectOption[] => {
    const listed = new Set((facets?.groups ?? []).flatMap((group) => group.types));
    const strays = entityTypes.filter((type) => !listed.has(type));
    const known = facets?.groups ?? [];
    const toggle = (list: string[], set: (value: string[]) => void, value: string) =>
      set(list.includes(value) ? list.filter((item) => item !== value) : [...list, value]);
    const options: MultiSelectOption[] = [];
    const sectionTitle = { records: strings.history.sectionRecords, metadata: strings.history.sectionMetadata };
    let lastSection: string | null = null;
    for (const group of known) {
      const groupChosen = groups.includes(group.key);
      options.push({
        value: group.key, label: group.label, optionLabel: group.label, heading: true, checked: groupChosen,
        section: group.section !== lastSection ? sectionTitle[group.section] : undefined,
        onToggle: () => toggle(groups, setGroups, group.key),
      });
      lastSection = group.section;
      [...group.types]
        .map((value) => ({ value, label: activityEntityLabel(value, orgLabelCap) }))
        .sort((a, b) => a.label.localeCompare(b.label))
        .forEach(({ value, label }) => options.push({
          value, label, optionLabel: label, indent: true, checked: groupChosen || entityTypes.includes(value), disabled: groupChosen,
          onToggle: () => toggle(entityTypes, setEntityTypes, value),
        }));
    }
    strays.forEach((value) => options.push({
      value, label: activityEntityLabel(value, orgLabelCap), optionLabel: activityEntityLabel(value, orgLabelCap), checked: true,
      onToggle: () => toggle(entityTypes, setEntityTypes, value),
    }));
    return options;
  }, [facets, entityTypes, groups, orgLabelCap, strings.history.sectionRecords, strings.history.sectionMetadata, setEntityTypes, setGroups]);

  const filtered = Boolean(period || entityTypes.length || groups.length || kinds.length || actors.length || includeComments);
  function clearFilters() {
    setPeriod("");
    setSince("");
    setUntil("");
    setEntityTypes([]);
    setGroups([]);
    setKinds([]);
    setActors([]);
    setIncludeComments(false);
  }

  const rows = useMemo(() => toActivityRows(entries ?? []), [entries]);
  const shown = useActivityColumnChoice("project_history", projectId);

  const emptyState = (
    <div className="stack" style={{ alignItems: "flex-start" }}>
      <p className="text-muted" style={{ margin: 0 }}>{filtered ? strings.history.emptyFiltered : strings.history.empty}</p>
      {filtered && <button type="button" className="btn" onClick={clearFilters}>{strings.history.clearFilters}</button>}
    </div>
  );

  return (
    <ListPageLayout
      title={strings.history.title}
      ready={entries !== null} columnChooser={shown.chooser}
      loadedRows={entries?.length}
      actions={projectId && (
        <ListExportMenu
          label={strings.history.exportLabel}
          exportFile={(kind) => {
            const params = filterParams();
            params.set("format", kind);
            return api.getForBlob(`/api/v1/projects/${projectId}/changes/export?${params.toString()}`);
          }}
        />
      )}
      filter={(
        <FilterPanel sectionKey="project-history" total={facets?.total ?? total} matching={total}>
          <PeriodFilter
            period={period} since={since} until={until} onPeriod={setPeriod} onSince={setSince} onUntil={setUntil}
          />
          <FilterField label={strings.history.entityType} help={strings.history.help.type}>
            <MultiSelectDropdown
              triggerLabel={strings.history.entityType} emptyLabel={strings.history.allEntityTypes} summaryLimit={2}
              filterable options={typeOptions}
            />
          </FilterField>
          <FilterField label={strings.history.kind} help={strings.history.help.kind}>
            <MultiSelectDropdown
              triggerLabel={strings.history.kind} emptyLabel={strings.history.kindAny} summaryLimit={2}
              options={[...CHANGE_KINDS, ...kinds.filter((kind): kind is ActivityKind => kind in ACTIVITY_KIND_LABEL && !CHANGE_KINDS.includes(kind as ActivityKind))].map((kind) => ({
                value: kind,
                label: ACTIVITY_KIND_LABEL[kind],
                optionLabel: ACTIVITY_KIND_LABEL[kind],
                checked: kinds.includes(kind),
                onToggle: () => setKinds((current) => (current.includes(kind) ? current.filter((k) => k !== kind) : [...current, kind])),
              }))}
            />
          </FilterField>
          <PrincipalListField
            label={strings.history.person} ariaLabel={strings.history.personAriaLabel} help={strings.history.help.person}
            values={actorValues} orgUsers={[]} organizationId={organizationId} projectId={projectId}
            emptyText={strings.history.personEmpty} onChange={(refs) => setActors(refs.map(principalKey))}
          />
          <FilterCheckbox
            label={strings.history.includeComments} help={strings.history.help.comments}
            checked={includeComments} onChange={setIncludeComments}
          />
        </FilterPanel>
      )}
    >
      {entries === null ? <Spinner /> : (
        <div style={loading ? { opacity: 0.55 } : undefined} aria-busy={loading}>
          <ProjectActivityTable
            ariaLabel={strings.history.tableLabel}
            rows={rows} columns={shown.columns}
            projectId={projectId}
            sort={sort ?? { key: "time", direction: "desc" }}
            onSort={(key) => setSort(cycleSort(sort, key as (typeof SORT_KEYS)[number]))}
            total={total}
            onLoadMore={() => void loadChanges(entries.length, true)}
            emptyState={emptyState}
          />
        </div>
      )}
    </ListPageLayout>
  );
}
