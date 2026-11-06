/**
 * Module: hooks/useCreatableRecordTypes
 *
 * Which record types a person may create and link from a record's Links panel: each type a link type from the
 * page's record reaches (the server's link options, already filtered by restriction, enabled modules and what the
 * caller may link) that the owning module can create (`modules/linkedRecordCreators`) and, where the module declares
 * a `canCreate` check, that the caller may create. An empty list means the panel offers no create choice, so a
 * record never offers one that would be refused. The relationship that leads is the page record's module's preferred
 * one (`preferredLinkPhrases`), else a specific link type; the symmetric "Related to" leads only when it is all there is.
 */
import { useEffect, useMemo, useState } from "react";

import type { ArtefactLinksApi, ArtefactLinkTypeOption } from "../api/artefactLinks";
import { getLinkedRecordCreator, getPreferredLinkPhrase } from "../modules/linkedRecordCreators";

const NONE: CreatableRecordType[] = [];

/** A record type that can be created from the panel, with the relationships that reach it (the default first). */
export interface CreatableRecordType {
  type: string;
  label: string;
  options: ArtefactLinkTypeOption[];
}

/** The creatable record types and the relationships that reach each, from the page record's link options, the one to
 * use first leading: the page record's owner's preferred relationship (`preferredLinkPhrases`), else a specific one,
 * and the generic symmetric "Related to" only when it is all there is. */
function creatableTypes(options: ArtefactLinkTypeOption[], artefactType: string): CreatableRecordType[] {
  const byType = new Map<string, ArtefactLinkTypeOption[]>();
  for (const option of options) {
    for (const other of option.other_types) {
      if (getLinkedRecordCreator(other.type)) byType.set(other.type, [...(byType.get(other.type) ?? []), option]);
    }
  }
  const generic = (o: ArtefactLinkTypeOption) => o.forward_name === "Related to" && o.reverse_name === "Related to";
  return [...byType].map(([type, reaching]) => {
    const preferred = getPreferredLinkPhrase(artefactType, type);
    const rank = (o: ArtefactLinkTypeOption) => (o.phrase === preferred ? 0 : generic(o) ? 2 : 1);
    return { type, label: getLinkedRecordCreator(type)!.label, options: [...reaching].sort((a, b) => rank(a) - rank(b)) };
  }).sort((a, b) => a.label.localeCompare(b.label));
}

/**
 * The record types the caller may create and link from the page's record.
 *
 * @param projectId The project of the page's record.
 * @param artefactType The page record's registered artefact type.
 * @param artefactId The page record's id.
 * @param api The links API (injectable for stories and tests).
 * @param enabled False when the panel will not offer creating (links need a change request, or the caller cannot link);
 *   nothing is loaded then.
 * @returns The creatable types; empty while loading, when none exists or when `enabled` is false.
 */
export function useCreatableRecordTypes(
  projectId: string, artefactType: string, artefactId: string, api: ArtefactLinksApi, enabled: boolean,
): CreatableRecordType[] {
  const [options, setOptions] = useState<ArtefactLinkTypeOption[]>([]);
  useEffect(() => {
    if (!enabled) return;
    let live = true;
    api.options(projectId, artefactType, artefactId)
      .then((rows) => { if (live) setOptions(rows); })
      .catch(() => { if (live) setOptions([]); });
    return () => { live = false; };
  }, [api, projectId, artefactType, artefactId, enabled]);

  const candidates = useMemo(() => creatableTypes(options, artefactType), [options, artefactType]);
  // The types the caller may create: a type with a `canCreate` check waits for it (and is left out while unknown or refused).
  const [allowed, setAllowed] = useState<string[]>([]);
  useEffect(() => {
    let live = true;
    Promise.all(candidates.map(async (c) => {
      const check = getLinkedRecordCreator(c.type)?.canCreate;
      if (!check) return c.type;
      try { return (await check(projectId)) ? c.type : null; } catch { return null; }
    })).then((types) => { if (live) setAllowed(types.filter((t): t is string => t !== null)); });
    return () => { live = false; };
  }, [candidates, projectId]);
  const creatable = useMemo(() => candidates.filter((c) => allowed.includes(c.type)), [candidates, allowed]);
  return enabled ? creatable : NONE;
}
