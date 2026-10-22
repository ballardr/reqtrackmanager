/**
 * Module: modules/risk_management/RiskFormModal
 *
 * Create/edit dialog for a risk's content fields, shared by the register
 * (create) and the detail page (edit) and told apart by whether `initial` is
 * passed — the convention `DecisionFormModal` uses. Inherent and residual
 * Likelihood/Consequence/Detectability levels are picked with the shared
 * `ScoringLevelPicker`, so the level names and guidance come from the project's
 * configured scheme; the rating itself is derived by the backend and never
 * entered here.
 *
 * On an Accepted risk the backend locks the levels, treatment strategy and
 * acceptance criteria (move it back to Assessed to change them), so those
 * controls are disabled with an explanation instead of failing on save. Edit
 * mode asks for an optional change note, stored on the new version.
 */
import { useState } from "react";

import type { ScoringScheme } from "../../api/scoring";
import type { OrgUser } from "../../api/types";
import { savedPrincipalDisplay, userPrincipal } from "../../api/types";
import type { CollectedLink } from "../../api/artefactLinks";
import { FormActions } from "../../components/FormActions";
import { DateField, TextAreaField, TextField } from "../../components/FormFields";
import { FormGrid, FormGridFull } from "../../components/FormGrid";
import { LabeledSelect } from "../../components/LabeledSelect";
import { PrincipalFormField } from "../../components/PrincipalFormField";
import { Modal } from "../../components/Modal";
import { QuickLinkField } from "../../components/QuickLinkField";
import { TagField } from "../../components/TagField";
import { ScoringLevelPicker } from "../../components/ScoringLevelPicker";
import { blankRiskValues, valuesFromRisk } from "./riskFields";
import { CONSEQUENCE_AXIS, DETECTABILITY_AXIS, findAxis, LIKELIHOOD_AXIS } from "./useRiskScheme";
import { TREATMENT_STRATEGY_LABEL } from "./types";
import type { Risk, RiskFieldValues, TreatmentStrategy } from "./types";
import { RISK_HELP } from "./help";

type LevelKey = Extract<keyof RiskFieldValues, `${"inherent" | "residual"}_${string}_level_id`>;

const AXES = [
  { axis: LIKELIHOOD_AXIS, suffix: "likelihood" },
  { axis: CONSEQUENCE_AXIS, suffix: "consequence" },
  { axis: DETECTABILITY_AXIS, suffix: "detectability" },
] as const;

/**
 * @param initial The risk being edited; omit to create.
 * @param scheme The project's effective `risk` scheme (null while loading: the level pickers are omitted).
 * @param riskTypes The enabled project risk types.
 * @param orgUsers Org users offered as owner (groups are listed by the picker itself).
 * @param organizationId The project's organisation, for user search and organisation groups.
 * @param projectId The risk's project, for project groups.
 * @param currentUserId Default owner (a user) for a new risk.
 * @param error A save error to show.
 * @param onSave Called with the form values, the change note (edit mode only) and the records chosen in the
 *   quick-link field (create mode only; empty when editing).
 */
export function RiskFormModal({
  initial, scheme, riskTypes, orgUsers, organizationId, projectId, currentUserId, error, onCancel, onSave,
}: {
  initial?: Risk;
  scheme: ScoringScheme | null;
  riskTypes: { id: string; name: string }[];
  orgUsers: OrgUser[];
  organizationId: string;
  projectId: string;
  currentUserId?: string;
  error?: string | null;
  onCancel: () => void;
  onSave: (values: RiskFieldValues, changeNote: string, quickLinks: CollectedLink[], tags: string[]) => void;
}) {
  const [values, setValues] = useState<RiskFieldValues>(() =>
    initial ? valuesFromRisk(initial) : blankRiskValues(userPrincipal(currentUserId)));
  const [changeNote, setChangeNote] = useState("");
  const [quickLinks, setQuickLinks] = useState<CollectedLink[]>([]);
  const [tags, setTags] = useState<string[]>([]);
  const set = <K extends keyof RiskFieldValues>(key: K, value: RiskFieldValues[K]) =>
    setValues((prev) => ({ ...prev, [key]: value }));

  const locked = initial?.status === "accepted";
  const valid = values.title.trim() !== "";

  function textField(key: "statement" | "cause" | "risk_event" | "consequence" | "acceptance_criteria", label: string, disabled = false) {
    return (
      <FormGridFull>
        <TextAreaField helpNotNeeded label={label} value={values[key]} onChange={(value) => set(key, value)} disabled={disabled} />
      </FormGridFull>
    );
  }

  function levelGroup(basis: "inherent" | "residual", heading: string) {
    return (
      <FormGridFull>
        <fieldset className="stack" style={{ border: "none", padding: 0, margin: 0 }}>
          <legend style={{ fontWeight: 600 }}>{heading}</legend>
          <div className="row" style={{ gap: "var(--space-5)", flexWrap: "wrap", alignItems: "flex-start" }}>
            {AXES.map(({ axis, suffix }) => {
              const found = findAxis(scheme, axis);
              if (!found) return null;
              const key = `${basis}_${suffix}_level_id` as LevelKey;
              return (
                <ScoringLevelPicker
                  key={key}
                  axis={{ ...found, label: `${heading} ${found.label.toLowerCase()}` }}
                  value={values[key]}
                  onChange={(levelId) => set(key, levelId)}
                  disabled={locked}
                />
              );
            })}
          </div>
        </fieldset>
      </FormGridFull>
    );
  }

  return (
    <Modal title={initial ? `Edit ${initial.unique_code}` : "New risk"} onClose={onCancel} size="lg">
      <div className="stack">
        <FormGrid minColumn="18rem">
          <FormGridFull>
            <TextField helpNotNeeded required label="Risk title" value={values.title} onChange={(value) => set("title", value)} />
          </FormGridFull>
          {textField("statement", "Risk statement")}
          {textField("cause", "Cause")}
          {textField("risk_event", "Risk event")}
          {textField("consequence", "Consequence")}
          <LabeledSelect helpNotNeeded
            label="Risk type"
            value={values.risk_type_id ?? ""}
            onChange={(next) => set("risk_type_id", next || null)}
            options={riskTypes.map((t) => ({ value: t.id, label: t.name }))}
            placeholder="No type"
          />
          <PrincipalFormField helpNotNeeded
            label="Owner"
            orgUsers={orgUsers}
            organizationId={organizationId}
            projectId={projectId}
            value={values.owner}
            display={savedPrincipalDisplay(values.owner, initial?.owner)}
            onChange={(next) => set("owner", next)}
            ariaLabel="Owner"
            placeholder="Search users and groups…"
            clearLabel="Clear"
          />
          {levelGroup("inherent", "Inherent")}
          {levelGroup("residual", "Residual")}
          <LabeledSelect help={RISK_HELP.riskTreatmentStrategy}
            label="Treatment strategy"
            value={values.treatment_strategy ?? ""}
            onChange={(next) => set("treatment_strategy", (next || null) as TreatmentStrategy | null)}
            options={Object.entries(TREATMENT_STRATEGY_LABEL).map(([value, label]) => ({ value, label }))}
            placeholder="Not decided"
            disabled={locked}
          />
          <DateField helpNotNeeded
            label="Next review date" ariaLabel="Next review date"
            value={values.review_date ?? ""} onChange={(value) => set("review_date", value || null)}
          />
          {textField("acceptance_criteria", "Acceptance criteria", locked)}
          {locked && (
            <FormGridFull>
              <p className="text-muted" style={{ margin: 0 }}>
                This risk is Accepted, so its levels, treatment strategy and acceptance criteria are locked. Move it back to
                Assessed to change them.
              </p>
            </FormGridFull>
          )}
          {initial && (
            <FormGridFull>
              <TextField helpNotNeeded label="Change note" ariaLabel="Change note" value={changeNote} onChange={setChangeNote} />
            </FormGridFull>
          )}
          {!initial && (
            <FormGridFull>
              <div className="stack">
                <QuickLinkField
                projectId={projectId} artefactType="risk" value={quickLinks} onChange={setQuickLinks}
              />
                <TagField projectId={projectId} artefactType="risk" value={tags} onChange={setTags} />
              </div>
            </FormGridFull>
          )}
        </FormGrid>
        <FormActions error={error} onCancel={onCancel} onSave={() => onSave(values, changeNote, quickLinks, tags)} saveDisabled={!valid} />
      </div>
    </Modal>
  );
}
