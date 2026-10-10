/**
 * Module: components/AddArtefactLinkModal
 *
 * The "Add a link" dialog of the shared Links panel (`ArtefactLinksPanel`): choose
 * where the other record lives (this project, or an ancestor or descendant), what
 * kind of record it is, how it relates, and which record. A Modal rather than an
 * inline row because the aside is narrow and the form has four dependent fields
 * (style guide: a create flow is a layer, not a reflow of the page).
 *
 * Everything offered comes from the server and is filtered there: the relationship
 * choices are the link types usable from this artefact (restrictions, artefact-type
 * rules, hiding and the nesting scope already applied), the record types are those
 * the chosen relationships can reach, and the records are the ones the user may see.
 * The server re-checks all of it when the link is created.
 *
 * In `changeRequest` mode (the page artefact is an approved requirement in a project
 * that needs a change request for link changes) only requirements of the same project
 * can be proposed, because that is what an `add_link` change request carries; the
 * dialog asks for the reason and hands the link to `changeRequest.onPropose`.
 */
import { useEffect, useMemo, useState } from "react";

import type {
  ArtefactLinkCandidates, ArtefactLinksApi, ArtefactLinkTypeOption, LinkCandidateProject, NewArtefactLink,
} from "../api/artefactLinks";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { LabeledSelect } from "./LabeledSelect";
import { Modal } from "./Modal";

/** Lets a page route link changes through a change request instead of the link endpoints. */
export interface LinksChangeRequestMode {
  /** Submits a change request proposing `link` (a same-project requirement); resolves once created. */
  onPropose: (link: NewArtefactLink, reason: string) => Promise<void>;
  /** Submits a change request proposing to remove the link `linkId`; resolves once created. */
  onProposeRemove: (linkId: string, reason: string) => Promise<void>;
}

const REQUIREMENT = "requirement";
const SEARCH_DEBOUNCE_MS = 250;

function optionKey(option: ArtefactLinkTypeOption): string {
  return `${option.link_type_id}:${option.direction}`;
}

/** The relationship to preselect for a record type: the symmetric "Related to" when offered, else the first. */
function defaultOptionKey(options: ArtefactLinkTypeOption[], otherType: string): string {
  const usable = options.filter((o) => o.other_types.some((t) => t.type === otherType));
  const related = usable.find((o) => o.forward_name === "Related to" && o.reverse_name === "Related to");
  return optionKey(related ?? usable[0] ?? ({ link_type_id: "", direction: "outgoing" } as ArtefactLinkTypeOption));
}

export function AddArtefactLinkModal({
  projectId,
  artefactType,
  artefactId,
  api,
  changeRequest,
  onAdded,
  onClose,
}: {
  projectId: string;
  artefactType: string;
  artefactId: string;
  api: ArtefactLinksApi;
  changeRequest?: LinksChangeRequestMode;
  /** Called after the link (or change request) is created. */
  onAdded: () => void;
  onClose: () => void;
}) {
  const strings = useStrings();
  const { showToast } = useToast();
  const [relatedProjects, setRelatedProjects] = useState<LinkCandidateProject[]>([]);
  const [otherProjectId, setOtherProjectId] = useState("");
  const [options, setOptions] = useState<ArtefactLinkTypeOption[] | null>(null);
  const [otherType, setOtherType] = useState("");
  const [chosenKey, setChosenKey] = useState("");
  const [searchText, setSearchText] = useState("");
  // Tagged with the search it answers, so a slow reply for an earlier search is never shown for a later one.
  const [loaded, setLoaded] = useState<{ key: string; result: ArtefactLinkCandidates } | null>(null);
  const [targetId, setTargetId] = useState("");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);

  // Where the other record may live. Not offered when proposing through a change request.
  useEffect(() => {
    if (changeRequest) return;
    let active = true;
    api.projects(projectId)
      .then((result) => {
        if (active) setRelatedProjects(result.items.filter((p) => p.relation !== "same" && !p.is_archived));
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [api, projectId, changeRequest]);

  // The relationships usable with the other end in the chosen project.
  useEffect(() => {
    let active = true;
    api.options(projectId, artefactType, artefactId, { otherProjectId: otherProjectId || undefined })
      .then((result) => {
        if (!active) return;
        const usable = changeRequest
          ? result.filter((o) => o.direction === "outgoing" && o.other_types.some((t) => t.type === REQUIREMENT))
          : result;
        setOptions(usable);
        const types = new Set(usable.flatMap((o) => o.other_types.map((t) => t.type)));
        const only = changeRequest ? REQUIREMENT : types.size === 1 ? [...types][0] : "";
        setOtherType(only);
        setChosenKey(only ? defaultOptionKey(usable, only) : "");
        setTargetId("");
        setSearchText("");
      })
      .catch((err) => {
        if (active) {
          setOptions([]);
          showToast(toErrorMessage(err, strings.artefactLinks.addFailed), "error");
        }
      });
    return () => {
      active = false;
    };
    // showToast and strings are stable enough for this fetch; refetching on them would loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, projectId, artefactType, artefactId, otherProjectId, changeRequest]);

  // The records of the chosen type, narrowed by the search text.
  const searchKey = `${otherProjectId}|${otherType}|${searchText.trim()}`;
  useEffect(() => {
    if (!otherType) return;
    let active = true;
    const timer = window.setTimeout(() => {
      api.candidates(projectId, artefactType, artefactId, {
        otherType, otherProjectId: otherProjectId || undefined, query: searchText.trim() || undefined,
      })
        .then((result) => {
          if (active) setLoaded({ key: searchKey, result });
        })
        .catch(() => {
          if (active) setLoaded({ key: searchKey, result: { items: [], truncated: false } });
        });
    }, searchText ? SEARCH_DEBOUNCE_MS : 0);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [api, projectId, artefactType, artefactId, otherType, otherProjectId, searchText, searchKey]);
  const candidates = otherType && loaded?.key === searchKey ? loaded.result : null;

  const typeChoices = useMemo(() => {
    const seen = new Map<string, string>();
    for (const option of options ?? []) for (const t of option.other_types) if (!seen.has(t.type)) seen.set(t.type, t.label);
    return [...seen].map(([value, label]) => ({ value, label })).sort((a, b) => a.label.localeCompare(b.label));
  }, [options]);
  const relationshipChoices = useMemo(
    () => (options ?? [])
      .filter((o) => o.other_types.some((t) => t.type === otherType))
      .map((o) => ({ value: optionKey(o), label: o.phrase })),
    [options, otherType],
  );
  const chosen = (options ?? []).find((o) => optionKey(o) === chosenKey);
  const reasonMissing = !!changeRequest && !reason.trim();

  async function submit() {
    if (!chosen || !targetId) return;
    const link: NewArtefactLink = {
      link_type_id: chosen.link_type_id, direction: chosen.direction, other_type: otherType, other_id: targetId,
      other_project_id: otherProjectId || undefined,
    };
    setSaving(true);
    try {
      if (changeRequest) await changeRequest.onPropose(link, reason.trim());
      else {
        await api.create(projectId, artefactType, artefactId, link);
        showToast(strings.artefactLinks.added);
      }
      onAdded();
    } catch (err) {
      showToast(toErrorMessage(err, strings.artefactLinks.addFailed), "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={strings.artefactLinks.addLinkTitle} onClose={onClose}>
      <div className="stack">
        {changeRequest && <p className="text-muted" style={{ margin: 0 }}>{strings.artefactLinks.changeRequestAddNotice}</p>}
        {relatedProjects.length > 0 && (
          <LabeledSelect
            label={strings.artefactLinks.projectLabel}
            value={otherProjectId}
            onChange={setOtherProjectId}
            placeholder={null}
            options={[
              { value: "", label: strings.artefactLinks.thisProject },
              ...relatedProjects.map((p) => ({ value: p.id, label: p.label })),
            ]}
          />
        )}
        {options !== null && options.length === 0 && <p className="text-muted" style={{ margin: 0 }}>{strings.artefactLinks.noTypes}</p>}
        {typeChoices.length > 1 && (
          <LabeledSelect
            label={strings.artefactLinks.otherTypeLabel}
            value={otherType}
            placeholder={strings.artefactLinks.otherTypePlaceholder}
            onChange={(value) => {
              setOtherType(value);
              setChosenKey(value ? defaultOptionKey(options ?? [], value) : "");
              setTargetId("");
              setSearchText("");
            }}
            options={typeChoices}
          />
        )}
        {otherType && (
          <>
            <LabeledSelect
              label={strings.artefactLinks.linkTypeLabel}
              value={chosenKey}
              onChange={setChosenKey}
              placeholder={null}
              options={relationshipChoices}
            />
            <label className="stack" style={{ gap: "0.25rem" }}>
              {strings.artefactLinks.searchLabel}
              <input
                className="input"
                aria-label={strings.artefactLinks.searchLabel}
                placeholder={strings.artefactLinks.searchPlaceholder}
                value={searchText}
                onChange={(e) => {
                  setSearchText(e.target.value);
                  setTargetId("");
                }}
              />
            </label>
            <LabeledSelect
              label={strings.artefactLinks.targetLabel}
              value={targetId}
              onChange={setTargetId}
              placeholder={strings.artefactLinks.targetPlaceholder}
              options={(candidates?.items ?? []).map((c) => ({ value: c.id, label: c.label }))}
            />
            {candidates !== null && candidates.items.length === 0 && (
              <p className="text-muted" style={{ margin: 0 }}>{strings.artefactLinks.noCandidates}</p>
            )}
            {candidates?.truncated && (
              <p className="text-muted" style={{ margin: 0 }}>{strings.artefactLinks.candidatesTruncated}</p>
            )}
          </>
        )}
        {changeRequest && (
          <label className="stack" style={{ gap: "0.25rem" }}>
            {strings.artefactLinks.reasonLabel}
            <textarea
              className="input" rows={2} aria-label={strings.artefactLinks.reasonLabel}
              value={reason} onChange={(e) => setReason(e.target.value)}
            />
          </label>
        )}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onClose}>{strings.common.cancel}</button>
          <button className="btn btn-primary" disabled={!chosen || !targetId || saving || reasonMissing} onClick={submit}>
            {changeRequest ? strings.artefactLinks.submitAddViaChangeRequest : strings.artefactLinks.submitAdd}
          </button>
        </div>
      </div>
    </Modal>
  );
}
