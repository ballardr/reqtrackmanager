/**
 * Module: components/AddArtefactLinkModal
 *
 * The "Add a link" dialog of the Links panel (`ArtefactLinksPanel`): a finder for the record, then the
 * relationship. A Modal because the aside is narrow and the fields are dependent (a create flow is a layer).
 *
 * The finder is a search box plus a scope narrowing step by step: nothing chosen searches every linkable type (two
 * characters or more); a chosen type limits the search; each browse level it declares (`api.browse`) narrows
 * further. No per-type code lives here. The relationship is chosen after the record from the link types usable
 * between the two; the server filters everything offered and re-checks it on creation.
 *
 * Two modes hand the link on instead of creating it: `changeRequest` (link changes need a request) asks for a
 * reason and calls `changeRequest.onPropose`; `collect` (a change request being drafted) calls `collect.onCollect`.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type {
  ArtefactLinkBrowseStep, ArtefactLinkCandidate, ArtefactLinkCandidates, ArtefactLinksApi, ArtefactLinkTypeOption,
  CollectedLink, LinkCandidateProject, NewArtefactLink,
} from "../api/artefactLinks";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { defaultOptionKey, optionKey } from "./linkOptions";
import { LabeledSelect } from "./LabeledSelect";
import { Modal } from "./Modal";
import { TextAreaField, TextField } from "./FormFields";
import { FormActions } from "./FormActions";

/** Lets a page route link changes through a change request instead of the link endpoints. */
export interface LinksChangeRequestMode {
  /** Submits a change request proposing `link`; resolves once created. */
  onPropose: (link: NewArtefactLink, reason: string) => Promise<void>;
  /** Submits a change request proposing to remove the link `linkId`; resolves once created. */
  onProposeRemove: (linkId: string, reason: string) => Promise<void>;
}

/** Hands the chosen link back to a form that holds it until the request is submitted. */
export interface LinksCollectMode {
  onCollect: (link: CollectedLink) => void;
}

const SEARCH_DEBOUNCE_MS = 250;
const GLOBAL_MIN_QUERY = 2;
const LEVEL_FILTER_THRESHOLD = 12;

/** One browse level of the chosen record type: what the server offered and what the user picked. */
interface Level extends ArtefactLinkBrowseStep {
  /** The chosen option id, or "" for "any". */
  value: string;
  /** Text typed into the level's own filter. */
  filter: string;
}

function chosenPairs(levels: Level[]): Array<[string, string]> {
  return levels.filter((l) => l.value).map((l) => [l.key, l.value]);
}

export function AddArtefactLinkModal({
  projectId,
  artefactType,
  artefactId,
  api,
  changeRequest,
  collect,
  onAdded,
  onClose,
}: {
  projectId: string;
  /** The page record's type. */
  artefactType: string;
  /** The page record's id, or `DRAFT_ARTEFACT_ID` for one that does not exist yet (`collect` only). */
  artefactId: string;
  api: ArtefactLinksApi;
  changeRequest?: LinksChangeRequestMode;
  collect?: LinksCollectMode;
  /** Called after the link (or change request) is created, or the link is collected. */
  onAdded: () => void;
  onClose: () => void;
}) {
  const strings = useStrings();
  const { showToast } = useToast();
  const [relatedProjects, setRelatedProjects] = useState<LinkCandidateProject[]>([]);
  const [otherProjectId, setOtherProjectId] = useState("");
  const [options, setOptions] = useState<ArtefactLinkTypeOption[] | null>(null);
  const [otherType, setOtherType] = useState("");
  const [levels, setLevels] = useState<Level[]>([]);
  const [searchText, setSearchText] = useState("");
  // Tagged with the search it answers, so a slow reply for an earlier search is never shown for a later one.
  const [loaded, setLoaded] = useState<{ key: string; result: ArtefactLinkCandidates } | null>(null);
  const [targetId, setTargetId] = useState("");
  const [chosenKey, setChosenKey] = useState("");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const levelRequest = useRef(0);
  const filterTimer = useRef<number | undefined>(undefined);

  // Where the other record may live: this project, its ancestors and its descendants.
  useEffect(() => {
    let active = true;
    api.projects(projectId)
      .then((result) => {
        if (active) setRelatedProjects(result.items.filter((p) => p.relation !== "same" && !p.is_archived));
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [api, projectId]);

  // The relationships usable with the other end in the chosen project.
  useEffect(() => {
    let active = true;
    api.options(projectId, artefactType, artefactId, { otherProjectId: otherProjectId || undefined })
      .then((result) => {
        if (!active) return;
        setOptions(result);
        const types = new Set(result.flatMap((o) => o.other_types.map((t) => t.type)));
        setOtherType(types.size === 1 ? [...types][0] : "");
        setLevels([]);
        setTargetId("");
        setChosenKey("");
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
  }, [api, projectId, artefactType, artefactId, otherProjectId]);

  /** Loads the level after `base` (the levels already chosen) and appends it; a stale reply is dropped. */
  const loadNextLevel = useCallback(
    (type: string, base: Level[]) => {
      const request = ++levelRequest.current;
      api.browse(projectId, artefactType, artefactId, {
        otherType: type, otherProjectId: otherProjectId || undefined, selected: chosenPairs(base),
      })
        .then((step) => {
          if (request === levelRequest.current) setLevels(step ? [...base, { ...step, value: "", filter: "" }] : base);
        })
        .catch(() => {
          if (request === levelRequest.current) setLevels(base);
        });
    },
    [api, projectId, artefactType, artefactId, otherProjectId],
  );

  // A new record type (or project) starts the cascade again from its first level; whatever changed
  // the type has already cleared the old levels. Waits for the relationships, whose arrival is what
  // settles the type, so a reply for a superseded project can never repopulate the levels.
  useEffect(() => {
    levelRequest.current += 1;
    if (options !== null && otherType) loadNextLevel(otherType, []);
  }, [loadNextLevel, otherType, options]);

  function chooseLevel(index: number, value: string) {
    const base = levels.slice(0, index + 1).map((level, i) => (i === index ? { ...level, value } : level));
    setLevels(base);
    setTargetId("");
    if (value) loadNextLevel(otherType, base);
    else levelRequest.current += 1;
  }

  /** Re-reads one level's options narrowed by the text typed into its own filter. */
  function filterLevel(index: number, text: string) {
    setLevels((current) => current.map((level, i) => (i === index ? { ...level, filter: text } : level)));
    window.clearTimeout(filterTimer.current);
    filterTimer.current = window.setTimeout(() => {
      api.browse(projectId, artefactType, artefactId, {
        otherType, otherProjectId: otherProjectId || undefined, selected: chosenPairs(levels.slice(0, index)),
        query: text.trim() || undefined,
      })
        .then((step) => {
          if (!step) return;
          setLevels((current) =>
            current.map((level, i) => (i === index ? { ...level, options: step.options, truncated: step.truncated } : level)),
          );
        })
        .catch(() => undefined);
    }, SEARCH_DEBOUNCE_MS);
  }

  // The records that match the scope and the search text. The chosen browse options travel as
  // `level:option,level:option` so the effect depends on a value, not a fresh array each render.
  const selectedKey = chosenPairs(levels).map(([key, option]) => `${key}:${option}`).join(",");
  const trimmedSearch = searchText.trim();
  const searchKey = `${otherProjectId}|${otherType}|${selectedKey}|${trimmedSearch}`;
  const searchable = !!otherType || trimmedSearch.length >= GLOBAL_MIN_QUERY;
  useEffect(() => {
    if (!searchable) return;
    let active = true;
    const selected = selectedKey
      ? selectedKey.split(",").map((part): [string, string] => [part.slice(0, part.indexOf(":")), part.slice(part.indexOf(":") + 1)])
      : undefined;
    const timer = window.setTimeout(() => {
      api.candidates(projectId, artefactType, artefactId, {
        otherType: otherType || undefined, otherProjectId: otherProjectId || undefined, selected,
        query: trimmedSearch || undefined,
      })
        .then((result) => {
          if (active) setLoaded({ key: searchKey, result });
        })
        .catch(() => {
          if (active) setLoaded({ key: searchKey, result: { items: [], truncated: false } });
        });
    }, trimmedSearch ? SEARCH_DEBOUNCE_MS : 0);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [api, projectId, artefactType, artefactId, otherType, otherProjectId, selectedKey, trimmedSearch, searchKey, searchable]);
  const candidates = searchable && loaded?.key === searchKey ? loaded.result : null;

  const typeChoices = useMemo(() => {
    const seen = new Map<string, string>();
    for (const option of options ?? []) for (const t of option.other_types) if (!seen.has(t.type)) seen.set(t.type, t.label);
    return [...seen].map(([value, label]) => ({ value, label })).sort((a, b) => a.label.localeCompare(b.label));
  }, [options]);

  const target: ArtefactLinkCandidate | undefined = candidates?.items.find((c) => c.id === targetId);
  const relationshipChoices = useMemo(
    () => (options ?? [])
      .filter((o) => target && o.other_types.some((t) => t.type === target.type))
      .map((o) => ({ value: optionKey(o), label: o.phrase })),
    [options, target],
  );
  const effectiveKey = target
    ? relationshipChoices.some((c) => c.value === chosenKey) ? chosenKey : defaultOptionKey(options ?? [], target.type)
    : "";
  const chosen = (options ?? []).find((o) => optionKey(o) === effectiveKey);
  const reasonMissing = !!changeRequest && !reason.trim();

  async function submit() {
    if (!chosen || !target) return;
    const link: NewArtefactLink = {
      link_type_id: chosen.link_type_id, direction: chosen.direction, other_type: target.type, other_id: target.id,
      other_project_id: otherProjectId || undefined,
    };
    setSaving(true);
    try {
      if (collect) {
        collect.onCollect({
          ...link, phrase: chosen.phrase, otherLabel: target.label, otherTypeLabel: target.type_label,
          otherProjectLabel: relatedProjects.find((p) => p.id === otherProjectId)?.label,
        });
      } else if (changeRequest) await changeRequest.onPropose(link, reason.trim());
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
          <LabeledSelect helpNotNeeded
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
        {options !== null && options.length > 0 && (
          <>
            {typeChoices.length > 1 && (
              <LabeledSelect helpNotNeeded
                label={strings.artefactLinks.otherTypeLabel}
                value={otherType}
                placeholder={strings.artefactLinks.otherTypePlaceholder}
                onChange={(value) => {
                  setOtherType(value);
                  setLevels([]);
                  setTargetId("");
                  setChosenKey("");
                }}
                options={typeChoices}
              />
            )}
            {levels.map((level, index) => (
              <div key={level.key} className="stack" style={{ gap: "var(--space-1)" }}>
                {(level.truncated || level.options.length > LEVEL_FILTER_THRESHOLD || level.filter) && (
                  <input
                    className="input"
                    aria-label={strings.artefactLinks.levelFilterLabel(level.label)}
                    placeholder={strings.artefactLinks.levelFilterLabel(level.label)}
                    value={level.filter}
                    onChange={(e) => filterLevel(index, e.target.value)}
                  />
                )}
                <LabeledSelect helpNotNeeded
                  label={level.label}
                  value={level.value}
                  placeholder={strings.artefactLinks.levelAny(level.label)}
                  onChange={(value) => chooseLevel(index, value)}
                  options={level.options.map((o) => ({ value: o.id, label: o.label }))}
                />
                {level.truncated && <span className="text-muted">{strings.artefactLinks.levelTruncated}</span>}
              </div>
            ))}
            <TextField helpNotNeeded
              label={strings.artefactLinks.searchLabel}
              value={searchText}
              onChange={(next) => {
                setSearchText(next);
                setTargetId("");
              }}
              placeholder={strings.artefactLinks.searchPlaceholder}
            />
            {!searchable && <p className="text-muted" style={{ margin: 0 }}>{strings.artefactLinks.searchPrompt}</p>}
            {searchable && (
              <LabeledSelect helpNotNeeded
                label={strings.artefactLinks.targetLabel}
                value={targetId}
                onChange={(value) => {
                  setTargetId(value);
                  setChosenKey("");
                }}
                placeholder={strings.artefactLinks.targetPlaceholder}
                options={(candidates?.items ?? []).map((c) => ({
                  value: c.id, label: otherType ? c.label : `${c.type_label}: ${c.label}`,
                }))}
              />
            )}
            {candidates !== null && candidates.items.length === 0 && (
              <p className="text-muted" style={{ margin: 0 }}>{strings.artefactLinks.noCandidates}</p>
            )}
            {candidates?.truncated && (
              <p className="text-muted" style={{ margin: 0 }}>{strings.artefactLinks.candidatesTruncated}</p>
            )}
            {target && (
              <LabeledSelect help={strings.help.linkRelationship}
                label={strings.artefactLinks.linkTypeLabel}
                value={effectiveKey}
                onChange={setChosenKey}
                placeholder={null}
                options={relationshipChoices}
              />
            )}
          </>
        )}
        {changeRequest && (
          <TextAreaField plainText="A link's reason is one line shown beside the link" helpNotNeeded label={strings.artefactLinks.reasonLabel} value={reason} onChange={setReason} rows={2} />
        )}
        <FormActions
          onCancel={onClose}
          onSave={submit}
          saveLabel={collect
              ? strings.artefactLinks.submitCollect
              : changeRequest ? strings.artefactLinks.submitAddViaChangeRequest : strings.artefactLinks.submitAdd}
          saveDisabled={!chosen || !target || saving || reasonMissing}
        />
      </div>
    </Modal>
  );
}
