/**
 * Module: components/RequirementPlaces
 *
 * The "Components and codes" section of a requirement's page: the places the requirement sits in, each with its
 * code (`SW-PERF-014` for its own place, `HW-IF-017` for a further one), and the actions on a further place.
 *
 * Responsibilities:
 * - List the own place and every alias with its code, through `RecordCode`.
 * - Add further places (a category picker) and remove one, which retires its code: it is never reused and still finds
 *   the requirement. Adding and removing are placement, so they follow an approved requirement's lock no more than a tag.
 * - Make a place the requirement's own (swapping the two places and their codes) and make an alias independent: a new
 *   requirement that takes the alias code. Both confirm first; making independent cannot be undone, so it asks for the
 *   code to be typed, names what is copied and reports afterwards what could not be.
 * - Say nothing for a requirement with no aliases when the viewer cannot add one or the project's setting disallows it.
 *
 * `api` is injectable for stories. `onChanged` lets the page reload what the change affects.
 */
import { ArrowUpRight, Repeat, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { artefactLinksApi, type ArtefactLinksApi, type ArtefactLinkTypeOption } from "../api/artefactLinks";
import { placementLabel, recordPlacementsApi, type PlacementPair, type RecordPlacementsApi } from "../api/placements";
import { requirementAliasesApi, type IndependentResult, type RequirementAliasesApi } from "../api/requirementAliases";
import type { Requirement, RequirementAlias } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { treeWithout, useRequirementAliasSetup } from "../hooks/useRequirementAliasSetup";
import { ActionMenu, type ActionMenuItem } from "./ActionMenu";
import { Badge } from "./Badge";
import { ConfirmDialog } from "./ConfirmDialog";
import { DetailCard } from "./DetailCard";
import { LabeledSelect } from "./LabeledSelect";
import { Modal } from "./Modal";
import { PlacementPicker } from "./PlacementPicker";
import { RecordCode } from "./RecordCode";
import { withDetailRank } from "./detailCardOrder";

type Dialog =
  | { kind: "remove"; alias: RequirementAlias }
  | { kind: "promote"; alias: RequirementAlias }
  | { kind: "independent"; alias: RequirementAlias };

/** The link type that joins an independent copy to its original when the organisation has no "Related to" type of its own. */
function hasRelatedType(options: ArtefactLinkTypeOption[]): boolean {
  return options.some((o) => o.direction === "outgoing" && o.flow === "none" && o.forward_name === o.reverse_name);
}

/**
 * The confirmation for making an alias independent (it cannot be undone, so the alias code is typed). It reads the
 * link types usable between two requirements and, only when the organisation has no symmetric type without a
 * direction ("Related to"), asks which type joins the new requirement to the original.
 */
function MakeIndependentDialog({
  projectId, requirement, alias, linksApi, onConfirm, onCancel,
}: {
  projectId: string;
  requirement: Requirement;
  alias: RequirementAlias;
  linksApi: ArtefactLinksApi;
  onConfirm: (relatedLinkTypeId?: string) => void;
  onCancel: () => void;
}) {
  const text = useStrings().requirementAliases;
  const [linkTypes, setLinkTypes] = useState<ArtefactLinkTypeOption[] | null>(null);
  const [chosen, setChosen] = useState("");
  useEffect(() => {
    let active = true;
    linksApi.options(projectId, "requirement", requirement.id, { otherType: "requirement" })
      .then((options) => active && setLinkTypes(options))
      .catch(() => active && setLinkTypes([]));
    return () => {
      active = false;
    };
  }, [linksApi, projectId, requirement.id]);
  const needsLinkType = linkTypes !== null && !hasRelatedType(linkTypes);
  return (
    <ConfirmDialog
      title={text.independentTitle} confirmLabel={text.independentConfirm} requireTypedText={alias.unique_code}
      confirmDisabled={linkTypes === null || (needsLinkType && !chosen)}
      message={
        <div className="stack">
          <span>{text.independentMessage(alias.unique_code, requirement.unique_code)}</span>
          {needsLinkType && (
            <LabeledSelect
              required help={text.independentLinkTypeHelp} label={text.independentLinkTypeLabel} value={chosen} onChange={setChosen}
              options={(linkTypes ?? []).filter((o) => o.direction === "outgoing").map((o) => ({ value: o.link_type_id, label: o.forward_name }))}
            />
          )}
        </div>
      }
      onConfirm={() => onConfirm(needsLinkType ? chosen : undefined)} onCancel={onCancel}
    />
  );
}

/**
 * @param projectId The project the page is opened in.
 * @param requirement The requirement.
 * @param canPlace Whether the viewer may add and remove places (the authority to tag a requirement).
 * @param canEdit Whether the viewer may edit requirements (needed to make a place the own one or to make it independent).
 * @param onChanged Called after a change was saved, with the requirement as it is now.
 * @param api The calls (the live ones by default).
 * @param placementsApi Reads the project's tree (the live calls by default).
 * @param linksApi Reads the link types usable between two requirements (the live calls by default).
 */
export function RequirementPlaces({
  projectId, requirement, canPlace, canEdit, onChanged, api = requirementAliasesApi, placementsApi = recordPlacementsApi,
  linksApi = artefactLinksApi,
}: {
  projectId: string;
  requirement: Requirement;
  canPlace: boolean;
  canEdit: boolean;
  onChanged: (updated?: Requirement) => void;
  api?: RequirementAliasesApi;
  placementsApi?: RecordPlacementsApi;
  linksApi?: ArtefactLinksApi;
}) {
  const strings = useStrings();
  const text = strings.requirementAliases;
  const { showToast } = useToast();
  const { settings, tree } = useRequirementAliasSetup(projectId, api, placementsApi);
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<IndependentResult | null>(null);
  // The places the picker shows while a change is being saved, so a tick registers at once.
  const [pending, setPending] = useState<PlacementPair[] | null>(null);
  const aliases = useMemo(() => (requirement.aliases ?? []).filter((a) => !a.is_retired), [requirement.aliases]);
  const pairs: PlacementPair[] = aliases.map((a) => ({ component_id: a.component_id, category_id: a.category_id }));

  if (!tree) return null;
  const names = new Map<string, string>([...tree.components, ...tree.categories].map((item) => [item.id, item.name]));
  const placeText = (componentId: string, categoryId: string) =>
    placementLabel({ component_name: names.get(componentId) ?? "", category_name: names.get(categoryId) ?? null });
  const canAdd = canPlace && settings?.mode === "allowed";
  if (aliases.length === 0 && !canAdd) return null;

  /** Runs a change, then reports it: a toast for success, a toast for a refusal that leaves the page as it was. */
  async function run<T>(action: () => Promise<T>, done: (value: T) => void) {
    setBusy(true);
    try {
      done(await action());
    } catch (err) {
      showToast(text.saveFailed(toErrorMessage(err, strings.common.error)), "error");
    } finally {
      setBusy(false);
    }
  }

  async function setPlaces(next: PlacementPair[]) {
    setPending(next);
    await run(() => api.setPlaces(projectId, requirement.id, next), (updated) => onChanged(updated));
    setPending(null);
  }

  function menuFor(alias: RequirementAlias): ActionMenuItem[] {
    return [
      ...(canEdit ? [
        { label: text.makeIndependent, key: "independent", icon: <ArrowUpRight />, onSelect: () => setDialog({ kind: "independent", alias }) },
        { label: text.makePrimary, key: "promote", icon: <Repeat />, disabled: requirement.is_locked,
          title: requirement.is_locked ? strings.requirements.lockedNotice : undefined, onSelect: () => setDialog({ kind: "promote", alias }) },
      ] : []),
      ...(canPlace ? [{ label: text.remove, key: "remove", icon: <Trash2 />, danger: true, onSelect: () => setDialog({ kind: "remove", alias }) }] : []),
    ];
  }

  const options = treeWithout(tree, [requirement.category_id]);

  async function confirm(active: Dialog, relatedLinkTypeId?: string) {
    setDialog(null);
    if (active.kind === "remove") {
      await run(() => api.retire(projectId, requirement.id, active.alias.id), (updated) => {
        showToast(text.removed);
        onChanged(updated);
      });
    } else if (active.kind === "promote") {
      await run(() => api.promote(projectId, requirement.id, active.alias.id), (updated) => {
        showToast(text.promoted);
        onChanged(updated);
      });
    } else {
      await run(
        () => api.makeIndependent(projectId, requirement.id, active.alias.id, relatedLinkTypeId),
        (made) => {
          setResult(made);
          showToast(text.independentDone(made.unique_code));
          onChanged();
        },
      );
    }
  }

  const aliasCode = (alias: RequirementAlias) => <RecordCode code={alias.unique_code} />;
  return (
    <DetailCard heading={text.heading} help={strings.help.requirementAliases}>
      <ul className="stack" style={{ listStyle: "none", margin: 0, padding: 0, gap: "var(--space-2)" }}>
        <li className="row" style={{ gap: "var(--space-3)" }}>
          <span className="chip">{placeText(requirement.component_id, requirement.category_id)}</span>
          <span className="text-muted" aria-label={text.codeOf(requirement.unique_code)}><RecordCode code={requirement.unique_code} /></span>
          <Badge tone="muted">{text.ownPlace}</Badge>
        </li>
        {aliases.map((alias) => {
          const place = placeText(alias.component_id, alias.category_id);
          const items = menuFor(alias);
          return (
            <li key={alias.id} className="row" style={{ gap: "var(--space-3)" }}>
              <span className="chip">{place}</span>
              <span className="text-muted" aria-label={text.codeOf(alias.unique_code)}>{aliasCode(alias)}</span>
              <Badge tone="info">{text.aliasBadge}</Badge>
              {items.length > 0 && <ActionMenu triggerLabel={text.actionsOf(alias.unique_code)} items={items} disabled={busy} size="sm" />}
            </li>
          );
        })}
      </ul>
      {canAdd && options.categories.length > 0 && (
        <PlacementPicker tree={options} categoryOnly value={pending ?? pairs} onChange={(next) => void setPlaces(next)} />
      )}

      {dialog?.kind === "remove" && (
        <ConfirmDialog
          title={text.removeTitle} confirmLabel={text.removeConfirm}
          message={text.removeMessage(dialog.alias.unique_code, placeText(dialog.alias.component_id, dialog.alias.category_id))}
          onConfirm={() => void confirm(dialog)} onCancel={() => setDialog(null)}
        />
      )}
      {dialog?.kind === "promote" && (
        <ConfirmDialog
          title={text.promoteTitle} confirmLabel={text.promoteConfirm}
          message={text.promoteMessage(dialog.alias.unique_code, requirement.unique_code)}
          onConfirm={() => void confirm(dialog)} onCancel={() => setDialog(null)}
        />
      )}
      {dialog?.kind === "independent" && (
        <MakeIndependentDialog
          projectId={projectId} requirement={requirement} alias={dialog.alias} linksApi={linksApi}
          onConfirm={(relatedLinkTypeId) => void confirm(dialog, relatedLinkTypeId)} onCancel={() => setDialog(null)}
        />
      )}
      {result && (
        <Modal title={text.independentDone(result.unique_code)} onClose={() => setResult(null)}>
          <div className="stack">
            {result.skipped.length > 0 ? (
              <>
                <p style={{ margin: 0 }}>{text.independentSkippedIntro(result.unique_code)}</p>
                <ul style={{ margin: 0 }}>
                  {result.skipped.map((item, index) => (
                    <li key={`${item.kind}:${item.label}:${index}`}>
                      {text.independentSkippedKind[item.kind]}: {item.label}. {item.reason}
                    </li>
                  ))}
                </ul>
              </>
            ) : null}
            <div className="row">
              <Link className="btn btn-primary" to={`/projects/${projectId}/requirements/${result.requirement_id}`}>{text.independentOpen}</Link>
              <button type="button" className="btn" onClick={() => setResult(null)}>{text.independentClose}</button>
            </div>
          </div>
        </Modal>
      )}
    </DetailCard>
  );
}

withDetailRank(RequirementPlaces, "organising");
