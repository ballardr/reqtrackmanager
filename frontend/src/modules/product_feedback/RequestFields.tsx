/**
 * Module: modules/product_feedback/RequestFields
 *
 * The fields of an enhancement request, shared by the create and the edit form (`RequestFormModal`) so a field
 * added later reaches both: title, description, owner and the scoring levels, plus the external references on a
 * create (an existing request's references change on its page, as they are not versions of it). The form owns the
 * draft; this component only edits it.
 *
 * Scoring levels are built from the scheme's axes, so an axis an organisation or project defines appears with no
 * change here. A derived axis (Demand) is worked out from the request's requesters and is shown with that level
 * as its placeholder; choosing a level overrides it and clearing the choice goes back to the worked-out one.
 * Inbox requests (no `projectId`) offer the same fields; the scheme passed in is the organisation's own.
 *
 * Layout: title and description take the row; the owner shares a row with `beside` (tags on a create, the change
 * note on an edit); the criteria pickers sit in one wrapping grid (titled Criteria) and the live scores, in their own block titled Scores, come after them, so each
 * choice shows its effect before saving.
 */
import type { ReactNode } from "react";

import type { ScoringScheme } from "../../api/scoring";
import type { OrgUser, Principal } from "../../api/types";
import { savedPrincipalDisplay } from "../../api/types";
import { TextAreaField, TextField } from "../../components/FormFields";
import { FormGridFull } from "../../components/FormGrid";
import { LabeledSelect } from "../../components/LabeledSelect";
import { PrincipalFormField } from "../../components/PrincipalFormField";
import { ScoringLevelPicker } from "../../components/ScoringLevelPicker";
import { PRODUCT_FEEDBACK_HELP } from "./help";
import { ReferencesField } from "./ReferencesField";
import type { RequestDraft } from "./requestDraft";
import { formAxes, isDerivedAxis, type LevelDraft } from "./requestLevels";
import { RequestScorePreview } from "./RequestScorePreview";
import { ScoringBlock } from "./ScoringBlock";
import type { ScorePreview } from "./types";
import type { ListChoice } from "./useFeedbackLists";
import { useScorePreview } from "./useScorePreview";

/**
 * @param draft The values being edited.
 * @param onChange Called with the next draft.
 * @param scheme The scoring scheme in effect (null while loading or when scoring cannot be read: the section is then left out).
 * @param derivedLevels The level each derived axis resolves to where none is chosen, by axis key (edit only).
 * @param orgUsers Organisation users offered as owner (groups are listed by the picker itself).
 * @param organizationId Enables server-side user search and organisation-group listing.
 * @param projectId Enables project-group choices; omit for an inbox request.
 * @param savedOwner The record's resolved owner, so a group the viewer cannot list still shows its name.
 * @param systems The external systems a new request's references can name; omit on an edit (no references field).
 * @param beside A field that shares the owner's row (tags on a create, the change note on an edit).
 * @param previewScores Scores levels still being chosen (the tier's `previewScores`, bound to its id); omit to show no scores.
 * @param requestId The request being edited, so the preview reads its weighted demand.
 */
export function RequestFields({
  draft, onChange, scheme, derivedLevels = {}, orgUsers, organizationId, projectId, savedOwner, systems, beside, previewScores,
  requestId,
}: {
  draft: RequestDraft;
  onChange: (next: RequestDraft) => void;
  scheme: ScoringScheme | null;
  derivedLevels?: Record<string, string>;
  orgUsers: OrgUser[];
  organizationId?: string;
  projectId?: string;
  savedOwner?: Principal | null;
  systems?: ListChoice[];
  beside?: ReactNode;
  previewScores?: (levels: LevelDraft, requestId?: string) => Promise<ScorePreview>;
  requestId?: string;
}) {
  const set = <K extends keyof RequestDraft>(key: K, value: RequestDraft[K]) => onChange({ ...draft, [key]: value });
  const setLevel = (axisKey: string, levelId: string | null) =>
    onChange({ ...draft, levels: { ...draft.levels, [axisKey]: levelId } });
  const axes = formAxes(scheme);

  return (
    <>
      <FormGridFull>
        <TextField helpNotNeeded required label="Title" ariaLabel="Request title" value={draft.title} onChange={(v) => set("title", v)} />
      </FormGridFull>
      <FormGridFull>
        <TextAreaField helpNotNeeded label="Description" rows={4} value={draft.description} onChange={(v) => set("description", v)} />
      </FormGridFull>
      <PrincipalFormField
        help={PRODUCT_FEEDBACK_HELP.requestOwner} label="Owner" orgUsers={orgUsers} organizationId={organizationId}
        projectId={projectId} value={draft.owner} display={savedPrincipalDisplay(draft.owner, savedOwner)}
        onChange={(next) => set("owner", next)} ariaLabel="Request owner" placeholder="Search users and groups…"
        clearLabel="Clear" kinds={projectId ? undefined : ["user", "org_group"]}
      />
      {beside}
      {axes.length > 0 && scheme && (
        <FormGridFull>
          <section className="stack" aria-label="Scoring">
            <strong>Scoring</strong>
            <ScoringBlock title="Criteria">
              <div
                style={{
                  display: "grid", gap: "var(--space-4) var(--space-5)", alignItems: "start",
                  gridTemplateColumns: "repeat(auto-fill, minmax(11.5rem, 1fr))",
                }}
              >
                {axes.map((axis) => isDerivedAxis(axis) ? (
                  <DerivedLevelPicker
                    key={axis.key} axis={axis} value={draft.levels[axis.key] ?? null}
                    derivedLevelId={derivedLevels[axis.key]} onChange={(next) => setLevel(axis.key, next)}
                  />
                ) : (
                  <ScoringLevelPicker
                    key={axis.key} axis={axis} value={draft.levels[axis.key] ?? null} onChange={(next) => setLevel(axis.key, next)}
                  />
                ))}
              </div>
            </ScoringBlock>
            {previewScores && (
              <ScoringBlock title="Scores">
                <ScorePreviewSection scheme={scheme} levels={draft.levels} fetchPreview={previewScores} requestId={requestId} />
              </ScoringBlock>
            )}
          </section>
        </FormGridFull>
      )}
      {systems && (
        <FormGridFull>
          <ReferencesField value={draft.references} onChange={(next) => set("references", next)} systems={systems} />
        </FormGridFull>
      )}
    </>
  );
}

/** The live scores under the pickers; its own component so the hook runs only where there is something to score. */
function ScorePreviewSection({
  scheme, levels, fetchPreview, requestId,
}: {
  scheme: ScoringScheme;
  levels: LevelDraft;
  fetchPreview: (levels: LevelDraft, requestId?: string) => Promise<ScorePreview>;
  requestId?: string;
}) {
  const state = useScorePreview(fetchPreview, levels, requestId);
  return <RequestScorePreview scheme={scheme} levels={levels} state={state} />;
}

/** A derived axis's picker: its placeholder names the worked-out level, and choosing one overrides it. */
function DerivedLevelPicker({
  axis, value, derivedLevelId, onChange,
}: {
  axis: ScoringScheme["axes"][number];
  value: string | null;
  derivedLevelId?: string;
  onChange: (levelId: string | null) => void;
}) {
  const derived = axis.levels.find((l) => l.id === derivedLevelId);
  const selected = axis.levels.find((l) => l.id === value) ?? null;
  return (
    <div className="stack" style={{ gap: "var(--space-1)" }}>
      <LabeledSelect
        help={PRODUCT_FEEDBACK_HELP.requestDerivedLevel} label={axis.label} value={value ?? ""}
        onChange={(next) => onChange(next || null)} options={axis.levels.map((l) => ({ value: l.id, label: l.name }))}
        placeholder={derived ? `Worked out: ${derived.name}` : "From demand"}
      />
      {selected?.description && <span className="text-muted" style={{ fontSize: "0.8rem" }}>{selected.description}</span>}
    </div>
  );
}
