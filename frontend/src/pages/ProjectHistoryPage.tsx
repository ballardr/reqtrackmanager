/**
 * Module: pages/ProjectHistoryPage
 *
 * The project's changes-over-time view (C-A-10): one table of what happened (Time, Type, Event, Record(s), Person),
 * newest first, narrowed by a side filter panel (period, type, change, person or group, discussion comments)
 * and downloadable as CSV, PDF, Word, ODT or ODS with the same filters.
 *
 * Responsibilities:
 * - Keep every filter and the sort in the URL (`hooks/useUrlFilter`), so Back from a record, a reload and a shared
 *   link restore the view, and `ListPageLayout` restores the scroll position and the rows loaded with "Show more".
 * - Read the page from `GET .../changes` (the server narrows and pages; nothing is filtered in the browser) and
 *   keep the previous rows, dimmed, while a changed filter loads, so the panel and table do not jump.
 * - Convert the person's local period to UTC instants (`utils/historyPeriod`); show each time in local time.
 *
 * Design decisions:
 * - A day is shown once, on the first row of each local day, with the time alone on the rows below it, so the
 *   Time column carries a date without repeating it on every row.
 * - The Event column and the record's Activity aside share one wording (`describeActivityAction`), so a change of
 *   text reaches both.
 * - The Person filter holds people and groups on parity (`PrincipalListField`); a group means its current members.
 *
 * External dependencies: `GET /api/v1/projects/{id}/changes` (+ `/facets`, `/actors`, `/export`).
 */
import { useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api/client";
import {
  ACTIVITY_KIND_LABEL, activityEntityLabel, activityEntryNotes, describeActivityAction, describeLinkEventAction, linkEventVerb,
  sentenceCase, type ActivityKind, type ChangeEntry, type Principal, type PrincipalRef,
} from "../api/types";
import { ActivityLinkEnds } from "../components/ActivityLinkEnds";
import { ActivityNote } from "../components/ActivityNote";
import { Badge } from "../components/Badge";
import { DirectoryTable, type DirectoryColumn } from "../components/DirectoryTable";
import { FilterCheckbox, FilterField, FilterPanel } from "../components/FilterPanel";
import { ListExportMenu } from "../components/ListExportMenu";
import { ListPageLayout } from "../components/ListPageLayout";
import { MultiSelectDropdown, type MultiSelectOption } from "../components/MultiSelectDropdown";
import { PeriodFilter } from "../components/PeriodFilter";
import { PrincipalListField } from "../components/PrincipalListField";
import { Spinner } from "../components/Spinner";
import { cycleSort } from "../components/sortState";
import { useOrgLabelCapitalized } from "../context/BrandingContext";
import { ProjectContext } from "../context/ProjectContextValue";
import { useStrings } from "../context/TerminologyContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { useRestoredRowCount } from "../hooks/useListPosition";
import { useUrlChoice, useUrlFlag, useUrlList, useUrlSort, useUrlText } from "../hooks/useUrlFilter";
import { activityRecordLink } from "../utils/activityLink";
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

/** One table row: the entry and whether it opens a new local day (so the day is written once). */
interface HistoryRow {
  key: string;
  entry: ChangeEntry;
  showDate: boolean;
}

/** The local calendar day of an instant, as `YYYY-MM-DD`, for grouping rows. */
function localDay(iso: string): string {
  const d = new Date(iso);
  return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;
}

/**
 * The table rows of `entries`: each with a React key that does not depend on position (a reload that inserts a
 * newer event shifts nothing) and whether it is the first of its local day.
 *
 * @param entries The loaded entries, in display order.
 */
function toRows(entries: ChangeEntry[]): HistoryRow[] {
  const seen = new Map<string, number>();
  return entries.map((entry, index) => {
    const base = `${entry.timestamp}|${entry.entity_type}|${entry.entity_id}|${entry.action}`;
    const occurrence = (seen.get(base) ?? 0) + 1;
    seen.set(base, occurrence);
    return {
      key: `${base}|${occurrence}`,
      entry,
      showDate: index === 0 || localDay(entry.timestamp) !== localDay(entries[index - 1].timestamp),
    };
  });
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

  const rows = useMemo(() => toRows(entries ?? []), [entries]);

  const columns: DirectoryColumn<HistoryRow>[] = [
    {
      key: "time",
      label: strings.history.columnTime,
      sortable: true,
      render: ({ entry, showDate }) => (
        <time dateTime={entry.timestamp} style={{ whiteSpace: "nowrap" }}>
          {showDate && <strong style={{ display: "block" }}>{new Date(entry.timestamp).toLocaleDateString(undefined, { dateStyle: "medium" })}</strong>}
          <span className="text-muted">{new Date(entry.timestamp).toLocaleTimeString()}</span>
        </time>
      ),
    },
    {
      key: "type",
      label: strings.history.columnType,
      render: ({ entry }) => <Badge>{activityEntityLabel(entry.entity_type, orgLabelCap)}</Badge>,
    },
    {
      key: "event",
      label: strings.history.columnEvent,
      width: "28%",
      render: ({ entry }) => (
        <span className="stack" style={{ gap: "0.15rem" }}>
          <span>{sentenceCase(describeLinkEventAction(entry) ?? describeActivityAction(entry, projectId))}</span>
          {activityEntryNotes(entry).map((note) => <ActivityNote key={note} text={note} />)}
        </span>
      ),
    },
    {
      key: "record",
      label: strings.history.columnRecord,
      width: "42%",
      render: ({ entry }) => {
        if (projectId && linkEventVerb(entry) !== null) return <ActivityLinkEnds entry={entry} projectId={projectId} />;
        const link = projectId ? activityRecordLink(entry, projectId) : null;
        if (link) return <Link to={link.to}>{link.label}</Link>;
        return entry.record_label ?? <span className="text-muted">—</span>;
      },
    },
    {
      key: "person",
      label: strings.history.columnPerson,
      render: ({ entry }) => (
        <span style={{ whiteSpace: "nowrap" }}>
          {entry.actor_display_name ?? <span className="text-muted">{strings.history.unnamedActor}</span>}
        </span>
      ),
    },
  ];

  const emptyState = (
    <div className="stack" style={{ alignItems: "flex-start" }}>
      <p className="text-muted" style={{ margin: 0 }}>{filtered ? strings.history.emptyFiltered : strings.history.empty}</p>
      {filtered && <button type="button" className="btn" onClick={clearFilters}>{strings.history.clearFilters}</button>}
    </div>
  );

  return (
    <ListPageLayout
      title={strings.history.title}
      ready={entries !== null}
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
          <DirectoryTable
            ariaLabel={strings.history.tableLabel}
            columns={columns}
            rows={rows}
            rowKey={(row) => row.key}
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
