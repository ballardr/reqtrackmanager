/**
 * Module: components/PolicyEditor
 *
 * The create/edit dialog for a policy: title (fixed for a built-in policy), effective date and the visual text
 * editor. Saving writes the working copy only; publishing is a separate, recorded action in `PoliciesPanel`, so an
 * edit never changes what people can already read.
 *
 * An organisation policy also takes an audience (users and organisation groups; empty is every member) and offers
 * starter titles that only fill the title field.
 *
 * The caller saves. The server's own rules (an unsafe link, an oversized text) come back as the error shown above
 * the form.
 */
import { useState } from "react";

import { api } from "../api/client";
import type { OrgPolicy, OrgPolicyWrite, Policy, PolicyBody, PolicySlot, Principal, PrincipalRef } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { FormActions } from "./FormActions";
import { DateField, TextField } from "./FormFields";
import { Modal } from "./Modal";
import { PolicyBodyEditor } from "./PolicyBodyEditor";
import { PrincipalListField } from "./PrincipalListField";

/** The principal kinds an organisation policy's audience may name (a project group belongs to one project). */
const AUDIENCE_KINDS = ["user", "org_group"] as const;

const EMPTY_BODY: PolicyBody = { type: "doc", content: [] };
/** The longest title the server accepts. */
const MAX_TITLE_LENGTH = 120;

/**
 * @param policy The policy being edited, or null to create one.
 * @param slot For a new built-in policy, its slot and fixed title; null for any other policy.
 * @param slotTitle The fixed title of `slot`.
 * @param error A save error to show.
 * @param organization For an organisation policy: its id and the title suggestions; omit for a server policy (which has
 *   no audience).
 * @param onCancel Called when the dialog is dismissed.
 * @param onSave Called with the fields.
 */
export function PolicyEditor({ policy, slot, slotTitle, error, organization, onCancel, onSave }: {
  policy: Policy | null;
  slot?: PolicySlot | null;
  slotTitle?: string;
  error?: string | null;
  organization?: { id: string; starterTitles: string[] };
  onCancel: () => void;
  onSave: (values: OrgPolicyWrite) => void;
}) {
  const strings = useStrings();
  const text = strings.policies;
  const fixedTitle = policy ? (policy.key ? policy.title : null) : (slotTitle ?? null);
  const [title, setTitle] = useState(policy?.title ?? slotTitle ?? "");
  const [body, setBody] = useState<PolicyBody>(policy?.body ?? EMPTY_BODY);
  const [effectiveFrom, setEffectiveFrom] = useState(policy?.effective_from ?? "");
  // The audience as display values; a person or group picked here is named by the server, so the chip never reads "Unknown".
  const [audience, setAudience] = useState<Principal[]>(() => (policy as OrgPolicy | null)?.audience ?? []);

  async function changeAudience(refs: PrincipalRef[]) {
    const held = new Map(audience.map((p) => [`${p.type}:${p.id}`, p]));
    const added = refs.filter((r) => !held.has(`${r.type}:${r.id}`));
    let named: Principal[] = [];
    if (organization && added.length > 0) {
      try {
        named = await api.post<Principal[]>(`/api/v1/orgs/${organization.id}/policies/audience-labels`, { audience: added });
      } catch {
        return; // The server refused the pick (not part of this organisation): leave the list as it was.
      }
    }
    const byKey = new Map([...held, ...named.map((p): [string, Principal] => [`${p.type}:${p.id}`, p])]);
    setAudience(refs.flatMap((r) => byKey.get(`${r.type}:${r.id}`) ?? []));
  }
  const suggestions = fixedTitle === null && !policy ? (organization?.starterTitles ?? []) : [];
  return (
    <Modal title={policy ? text.editPolicy : (slotTitle ? text.writeSlot(slotTitle) : text.newPolicy)} onClose={onCancel} size="lg">
      <div className="stack">
        {fixedTitle === null ? (
          <TextField
            helpNotNeeded required label={text.title} value={title} onChange={setTitle}
            inputProps={{ maxLength: MAX_TITLE_LENGTH, autoFocus: true }}
          />
        ) : (
          <TextField helpNotNeeded label={text.title} value={fixedTitle} onChange={() => undefined} inputProps={{ readOnly: true }} />
        )}
        {suggestions.length > 0 && title.trim() === "" && (
          <div className="row" style={{ gap: "var(--space-2)", flexWrap: "wrap" }} role="group" aria-label={text.titleSuggestions}>
            {suggestions.map((suggestion) => (
              <button key={suggestion} type="button" className="btn" onClick={() => setTitle(suggestion)}>{suggestion}</button>
            ))}
          </div>
        )}
        <DateField label={text.effectiveFromLabel} help={strings.help.policyEffectiveFrom} value={effectiveFrom} onChange={setEffectiveFrom} />
        {organization && (
          <PrincipalListField
            label={text.audience} ariaLabel={text.audience} values={audience} orgUsers={[]}
            organizationId={organization.id} kinds={AUDIENCE_KINDS} emptyText={text.audienceEmpty} help={strings.help.policyAudience}
            onChange={(refs) => void changeAudience(refs)}
          />
        )}
        <PolicyBodyEditor label={text.body} help={strings.help.policyBody} value={body} onChange={setBody} />
        <FormActions
          error={error} onCancel={onCancel} saveDisabled={fixedTitle === null && title.trim() === ""}
          onSave={() => onSave({
            key: policy ? undefined : (slot ?? null), title: title.trim(), body, effective_from: effectiveFrom === "" ? null : effectiveFrom,
            ...(organization ? { audience: audience.map(({ type, id }) => ({ type, id })) } : {}),
          })}
        />
      </div>
    </Modal>
  );
}
