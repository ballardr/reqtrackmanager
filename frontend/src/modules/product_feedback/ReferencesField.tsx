/**
 * Module: modules/product_feedback/ReferencesField
 *
 * The "External references" section of the create form: a list of references to items in outside tools (a Jira epic,
 * a ServiceNow ticket) to attach to the request as it is created, each laid out by the shared `ReferenceFields`.
 * An edit form does not show it: a reference is changed on the request page, on its own and without making a new
 * version of the request. Each row ends in a red icon-only remove button level with its fields. The form owns the list; a row with no system, or neither key nor link, is dropped on save.
 */
import { Plus, X } from "lucide-react";

import { BLANK_REFERENCE, type ReferenceDraft } from "./referenceDraft";
import { ReferenceFields } from "./ReferenceFields";
import type { ListChoice } from "./useFeedbackLists";

/**
 * @param value The references being added.
 * @param onChange Called with the next list.
 * @param systems The external systems that can be chosen.
 */
export function ReferencesField({
  value, onChange, systems,
}: { value: ReferenceDraft[]; onChange: (next: ReferenceDraft[]) => void; systems: ListChoice[] }) {
  return (
    <section className="stack" aria-label="External references">
      <strong>External references</strong>
      {value.map((draft, index) => (
        <div key={index} style={{ display: "flex", gap: "var(--space-2)", alignItems: "flex-start" }}>
          <div className="form-grid" style={{ "--form-grid-min": "10rem", flex: 1 } as React.CSSProperties}>
            <ReferenceFields
              draft={draft} systems={systems} label={`Reference ${index + 1}`}
              onChange={(next) => onChange(value.map((d, i) => (i === index ? next : d)))}
            />
          </div>
          {/* Level with the inputs, below their captions. */}
          <button
            type="button" className="btn btn-sm btn-icon btn-danger" style={{ marginTop: "1.65rem" }}
            title={`Remove reference ${index + 1}`} aria-label={`Remove reference ${index + 1}`}
            onClick={() => onChange(value.filter((_, i) => i !== index))}
          >
            <X />
          </button>
        </div>
      ))}
      <div>
        <button type="button" className="btn btn-sm" onClick={() => onChange([...value, BLANK_REFERENCE])}>
          <Plus size={14} aria-hidden="true" /> Add a reference
        </button>
      </div>
    </section>
  );
}
