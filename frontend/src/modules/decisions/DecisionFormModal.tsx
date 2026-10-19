/**
 * Module: modules/decisions/DecisionFormModal
 *
 * Create/edit dialog for a Decision's content fields — shared by
 * `ProjectDecisionsPage.tsx` (create) and `DecisionDetailPanel.tsx` (edit),
 * distinguished by whether `initial` is passed, the same convention
 * `modules/compliance/EvidencePanel.tsx`'s `EvidenceFormModal` and
 * `StandardFormModal.tsx` both already use.
 *
 * Create mode only: a Decision Template picker pre-fills the seven free-text fields with that template's
 * guidance prompts, editable immediately afterward — a creation-time
 * convenience only (`Decision` holds no FK back to the template used), so
 * edit mode has no template picker at all, and re-picking a template simply
 * overwrites the seven fields' current text (not merged/appended), matching
 * this module's own plan doc description of a template as "a starting
 * point, not a permanent link."
 */
import { useState } from "react";

import type { OrgUser, PrincipalRef } from "../../api/types";
import { principalRef, savedPrincipalDisplay, userPrincipal } from "../../api/types";
import type { CollectedLink } from "../../api/artefactLinks";
import { FormActions } from "../../components/FormActions";
import { DateField, TextAreaField, TextField } from "../../components/FormFields";
import { FormGrid, FormGridFull } from "../../components/FormGrid";
import { LabeledSelect } from "../../components/LabeledSelect";
import { Modal } from "../../components/Modal";
import { QuickLinkField } from "../../components/QuickLinkField";
import { TagField } from "../../components/TagField";
import { PrincipalFormField } from "../../components/PrincipalFormField";
import type { Decision, DecisionFieldValues, DecisionTemplate, DecisionTypeDefinition } from "./types";
import { DECISIONS_HELP } from "./help";

type PromptKey =
  | "context_prompt" | "options_considered_prompt" | "chosen_option_prompt" | "rationale_prompt"
  | "consequences_prompt" | "assumptions_prompt" | "constraints_prompt";

const PROMPT_TO_FIELD: { promptKey: PromptKey; fieldKey: keyof DecisionFieldValues; label: string }[] = [
  { promptKey: "context_prompt", fieldKey: "context", label: "Context" },
  { promptKey: "options_considered_prompt", fieldKey: "options_considered", label: "Options considered" },
  { promptKey: "chosen_option_prompt", fieldKey: "chosen_option", label: "Chosen option" },
  { promptKey: "rationale_prompt", fieldKey: "rationale", label: "Rationale" },
  { promptKey: "consequences_prompt", fieldKey: "consequences", label: "Consequences" },
  { promptKey: "assumptions_prompt", fieldKey: "assumptions", label: "Assumptions" },
  { promptKey: "constraints_prompt", fieldKey: "constraints", label: "Constraints" },
];

export function DecisionFormModal({
  initial,
  decisionTypes,
  templates,
  orgUsers,
  organizationId,
  projectId,
  currentUserId,
  error,
  onCancel,
  onSave,
}: {
  initial?: Decision;
  decisionTypes: DecisionTypeDefinition[];
  /** Only offered in create mode — omitted (or empty) hides the picker. */
  templates?: DecisionTemplate[];
  /** Organisation members, for the owner and decision maker pickers. */
  orgUsers: OrgUser[];
  /** Enables organisation-group listing and server-side user search. */
  organizationId: string;
  /** Enables project-group listing. */
  projectId: string;
  currentUserId?: string;
  error?: string | null;
  onCancel: () => void;
  onSave: (values: DecisionFieldValues, quickLinks: CollectedLink[], tags: string[]) => void;
}) {
  const [templateId, setTemplateId] = useState("");
  const [quickLinks, setQuickLinks] = useState<CollectedLink[]>([]);
  const [tags, setTags] = useState<string[]>([]);
  const [title, setTitle] = useState(initial?.title ?? "");
  const [statement, setStatement] = useState(initial?.decision_statement ?? "");
  const [decisionTypeId, setDecisionTypeId] = useState(initial?.decision_type_id ?? decisionTypes[0]?.id ?? "");
  // The types may arrive after this form opens (the page loads them in
  // parallel); adopt the first one then, or Save stays disabled for good
  // (found 2026-10-04 via the e2e suite under load). React's "adjust state
  // during render" pattern — converges in one extra render.
  if (decisionTypeId === "" && decisionTypes[0]) setDecisionTypeId(decisionTypes[0].id);
  const [decisionDate, setDecisionDate] = useState(initial?.decision_date ?? "");
  const [decisionMaker, setDecisionMaker] = useState<PrincipalRef | null>(principalRef(initial?.decision_maker));
  const [owner, setOwner] = useState<PrincipalRef | null>(initial ? principalRef(initial.owner) : userPrincipal(currentUserId));
  const [fields, setFields] = useState<Record<string, string>>(() =>
    Object.fromEntries(PROMPT_TO_FIELD.map((f) => [f.fieldKey, (initial?.[f.fieldKey] as string | null) ?? ""]))
  );

  function applyTemplate(id: string) {
    setTemplateId(id);
    const template = templates?.find((t) => t.id === id);
    if (!template) return;
    setFields(Object.fromEntries(PROMPT_TO_FIELD.map((f) => [f.fieldKey, template[f.promptKey] ?? ""])));
  }

  function save() {
    onSave({
      title,
      decision_statement: statement,
      decision_type_id: decisionTypeId,
      decision_date: decisionDate || null,
      decision_maker: decisionMaker,
      owner,
      ...(Object.fromEntries(PROMPT_TO_FIELD.map((f) => [f.fieldKey, fields[f.fieldKey] || null])) as Record<string, string | null>),
    } as DecisionFieldValues, quickLinks, tags);
  }

  const valid = title.trim() !== "" && statement.trim() !== "" && decisionTypeId !== "" && owner !== null;

  return (
    <Modal title={initial ? `Edit ${initial.unique_code}` : "New decision"} onClose={onCancel} size="lg">
      <div className="stack">
        <FormGrid minColumn="18rem">
          {!initial && templates && templates.length > 0 && (
            <FormGridFull>
              <LabeledSelect help={DECISIONS_HELP.decisionTemplate}
                label="Start from a template (optional)"
                value={templateId}
                onChange={applyTemplate}
                options={templates.map((t) => ({ value: t.id, label: t.name }))}
                placeholder="No template"
              />
            </FormGridFull>
          )}
          <FormGridFull>
            <TextField helpNotNeeded label="Decision title" value={title} onChange={setTitle} />
          </FormGridFull>
          <FormGridFull>
            <TextAreaField helpNotNeeded label="Decision statement" value={statement} onChange={setStatement} />
          </FormGridFull>
          <LabeledSelect helpNotNeeded
            label="Decision type"
            value={decisionTypeId}
            onChange={setDecisionTypeId}
            options={decisionTypes.map((t) => ({ value: t.id, label: t.name }))}
          />
          <DateField helpNotNeeded label="Decision date (optional)" value={decisionDate} onChange={setDecisionDate} />
          <PrincipalFormField helpNotNeeded
            label="Decision maker (optional)"
            orgUsers={orgUsers}
            organizationId={organizationId}
            projectId={projectId}
            value={decisionMaker}
            display={savedPrincipalDisplay(decisionMaker, initial?.decision_maker)}
            onChange={setDecisionMaker}
            ariaLabel="Decision maker"
            placeholder="Search users and groups…"
          />
          <PrincipalFormField helpNotNeeded
            label="Owner"
            orgUsers={orgUsers}
            organizationId={organizationId}
            projectId={projectId}
            value={owner}
            display={savedPrincipalDisplay(owner, initial?.owner)}
            onChange={setOwner}
            ariaLabel="Owner"
            placeholder="Select an owner…"
            clearLabel="Clear"
          />
          {PROMPT_TO_FIELD.map((f) => (
            <FormGridFull key={f.fieldKey}>
              <TextAreaField helpNotNeeded
                label={f.label} value={fields[f.fieldKey]}
                onChange={(value) => setFields((prev) => ({ ...prev, [f.fieldKey]: value }))}
              />
            </FormGridFull>
          ))}
          {!initial && (
            <FormGridFull>
              <div className="stack">
                <QuickLinkField
                projectId={projectId} artefactType="decision" preferredType="requirement" value={quickLinks} onChange={setQuickLinks}
              />
                <TagField projectId={projectId} artefactType="decision" value={tags} onChange={setTags} />
              </div>
            </FormGridFull>
          )}
        </FormGrid>
        <FormActions error={error} onCancel={onCancel} onSave={save} saveDisabled={!valid} />
      </div>
    </Modal>
  );
}
