/**
 * Module: components/CreateLinkedRecord
 *
 * The "Create new" control of the shared Links panel: creates a record of another type and links it to the page's
 * record in one step, so a person does not leave the page to make the thing they want to link to.
 *
 * Responsibilities:
 * - Offer each record type a link type from the page's record reaches (the server's link options, already filtered
 *   by restriction, enabled modules and what the caller may link) that the owning module can create
 *   (`modules/linkedRecordCreators`) and, where the module declares a `canCreate` check, that the caller may create;
 *   nothing at all renders when there is none, so a record never offers a control that would be refused.
 * - Show the owning module's own create dialog (core never imports a module's form), and link the new record with
 *   the chosen relationship once the dialog reports it.
 *
 * Design decisions:
 * - The relationship defaults to the one the page record's module prefers (`preferredLinkPhrases`: a request's
 *   Pain Points are the ones it "Addresses", which other features count), else the first specific link type; the
 *   symmetric "Related to" leads only when nothing else reaches the type. A select lists every relationship that
 *   reaches the type (shown only when there is more than one), so the person can choose another.
 * - Not offered while links need a change request (the page passes none of this then): the new record would have to
 *   be proposed, not linked.
 */
import { FilePlus } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { ArtefactLinksApi, ArtefactLinkTypeOption } from "../api/artefactLinks";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { getLinkedRecordCreator, getPreferredLinkPhrase } from "../modules/linkedRecordCreators";
import { AddPopoverButton } from "./AddPopoverButton";
import { optionKey } from "./linkOptions";

/** The creatable record types and the relationships that reach each, from the page record's link options, the one to
 * use first leading: the page record's owner's preferred relationship (`preferredLinkPhrases`), else a specific one,
 * and the generic symmetric "Related to" only when it is all there is. */
function creatableTypes(
  options: ArtefactLinkTypeOption[], artefactType: string,
): { type: string; label: string; options: ArtefactLinkTypeOption[] }[] {
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
 * @param projectId The project of the page's record.
 * @param artefactType The page record's registered artefact type.
 * @param artefactId The page record's id.
 * @param api The links API (injectable for stories and tests).
 * @param compact True for the icon-only form used by a panel inside another card.
 * @param onLinked Called after a new record is created and linked, so the panel reloads.
 */
export function CreateLinkedRecord({
  projectId, artefactType, artefactId, api, compact = false, onLinked,
}: {
  projectId: string;
  artefactType: string;
  artefactId: string;
  api: ArtefactLinksApi;
  compact?: boolean;
  onLinked: () => void;
}) {
  const strings = useStrings();
  const { showToast } = useToast();
  const [options, setOptions] = useState<ArtefactLinkTypeOption[] | null>(null);
  // The relationship chosen per type; a type not in here uses its first (most specific) one.
  const [chosen, setChosen] = useState<Record<string, string>>({});
  const [creating, setCreating] = useState<{ type: string; label: string; option: ArtefactLinkTypeOption } | null>(null);

  useEffect(() => {
    let live = true;
    api.options(projectId, artefactType, artefactId)
      .then((rows) => { if (live) setOptions(rows); })
      .catch(() => { if (live) setOptions([]); });
    return () => { live = false; };
  }, [api, projectId, artefactType, artefactId]);

  const candidates = useMemo(() => creatableTypes(options ?? [], artefactType), [options, artefactType]);
  // The types the caller may create: a type with a `canCreate` check waits for it (and is left out while unknown or refused).
  const [allowed, setAllowed] = useState<string[] | null>(null);
  useEffect(() => {
    let live = true;
    Promise.all(candidates.map(async (c) => {
      const check = getLinkedRecordCreator(c.type)?.canCreate;
      if (!check) return c.type;
      try { return (await check(projectId)) ? c.type : null; } catch { return null; }
    })).then((types) => { if (live) setAllowed(types.filter((t): t is string => t !== null)); });
    return () => { live = false; };
  }, [candidates, projectId]);
  const types = candidates.filter((c) => allowed?.includes(c.type));
  if (types.length === 0) return null;

  async function created(id: string) {
    const target = creating;
    setCreating(null);
    if (!target) return;
    try {
      await api.create(projectId, artefactType, artefactId, {
        link_type_id: target.option.link_type_id, direction: target.option.direction, other_type: target.type, other_id: id,
      });
      showToast(strings.artefactLinks.createdAndLinked(target.label));
    } catch (err) {
      showToast(`${strings.artefactLinks.createdNotLinked(target.label)} ${toErrorMessage(err, "")}`.trim(), "error");
    }
    onLinked();
  }

  return (
    <>
      <AddPopoverButton
        label={strings.artefactLinks.createNewTitle} icon={FilePlus} size={compact ? "sm" : "md"}
        text={compact ? undefined : strings.artefactLinks.createNew}
      >
        {(close) => (
          <div className="stack" style={{ gap: "var(--space-3)" }}>
            {types.map((entry) => {
              const selected = entry.options.find((o) => optionKey(o) === chosen[entry.type]) ?? entry.options[0];
              return (
                <div key={entry.type} className="stack" style={{ gap: "var(--space-1)" }}>
                  <button
                    type="button" className="btn btn-sm" style={{ alignSelf: "flex-start" }}
                    onClick={() => { close(); setCreating({ type: entry.type, label: entry.label, option: selected }); }}
                  >
                    {strings.artefactLinks.createNewOf(entry.label)}
                  </button>
                  {entry.options.length > 1 && (
                    <select
                      className="input" aria-label={`${entry.label} ${strings.artefactLinks.createNewRelationship}`} value={optionKey(selected)}
                      onChange={(e) => setChosen((c) => ({ ...c, [entry.type]: e.target.value }))}
                    >
                      {entry.options.map((o) => <option key={optionKey(o)} value={optionKey(o)}>{o.phrase}</option>)}
                    </select>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </AddPopoverButton>
      {creating && getLinkedRecordCreator(creating.type)?.render({
        projectId, onCreated: (id) => void created(id), onCancel: () => setCreating(null),
      })}
    </>
  );
}
