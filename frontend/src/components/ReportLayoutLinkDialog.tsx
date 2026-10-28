/**
 * Module: components/ReportLayoutLinkDialog
 *
 * The dialog that makes, changes or removes a link on the selected words in the document view: a web address, an
 * email address or a section (heading) of the same document.
 *
 * Responsibilities: offer the three kinds, build the address from the one chosen, check it with the same rules the
 * server applies (`linkProblem`) and show what is wrong, and hand back the finished address (`https://…`,
 * `mailto:…` or `#anchor`).
 *
 * Design decisions: a web address may hold a `{{placeholder}}`, which is only checkable once a record fills it in, so
 * the dialog accepts one and the report checks the result; every other address is checked here and again by the
 * server. A section is picked from the layout's own headings rather than typed, so a link cannot name a heading that
 * is not there.
 */
import { useState } from "react";

import { useStrings } from "../context/TerminologyContext";
import type { Section } from "../utils/reportLayoutDoc";
import { linkProblem } from "../utils/reportLayoutProse";
import { FormActions } from "./FormActions";
import { TextField } from "./FormFields";
import { LabeledSelect } from "./LabeledSelect";
import { Modal } from "./Modal";

type Kind = "web" | "email" | "section";

const kindOf = (href: string): Kind => (href.startsWith("#") ? "section" : href.toLowerCase().startsWith("mailto:") ? "email" : "web");

/** The address the dialog's fields stand for. */
function hrefOf(kind: Kind, address: string, email: string, anchor: string): string {
  return kind === "section" ? (anchor === "" ? "" : `#${anchor}`) : kind === "email" ? `mailto:${email.trim()}` : address.trim();
}

/** Why the address is not acceptable, or `null`; a web address holding a placeholder is judged once it is filled in. */
function problemWith(kind: Kind, href: string): string | null {
  if (kind !== "web" || !href.includes("{{")) return linkProblem(href);
  // A value will fill each placeholder in: judge the address as if one were there (a leading one may be the whole address).
  const filled = href.replace(/\{\{[^{}]*\}\}/g, "x");
  return linkProblem(href.startsWith("{{") ? `https://${filled}` : filled);
}

/**
 * @param initialHref The link's current address, or `""` for a new one.
 * @param sections The headings of the layout, for "a section of this document".
 * @param onApply Called with the finished address.
 * @param onRemove Called by "Remove link" (offered only when there is a link to remove).
 * @param onClose Called by Cancel.
 */
export function ReportLayoutLinkDialog({
  initialHref, sections, onApply, onRemove, onClose,
}: { initialHref: string; sections: Section[]; onApply: (href: string) => void; onRemove?: () => void; onClose: () => void }) {
  const text = useStrings().reportOutline;
  const startKind = initialHref === "" ? "web" : kindOf(initialHref);
  const [kind, setKind] = useState<Kind>(startKind);
  const [address, setAddress] = useState(startKind === "web" ? initialHref : "");
  const [email, setEmail] = useState(startKind === "email" ? initialHref.slice(7).split("?")[0] : "");
  const [anchor, setAnchor] = useState(startKind === "section" ? initialHref.slice(1) : "");
  const href = hrefOf(kind, address, email, anchor);
  const problem = href === "" || href === "mailto:" ? null : problemWith(kind, href);
  const unknownSection = kind === "section" && anchor !== "" && !sections.some((s) => s.anchor === anchor);

  return (
    <Modal title={text.linkTitle} onClose={onClose}>
      <div className="stack">
        <LabeledSelect helpNotNeeded required
          label={text.linkKind} value={kind} placeholder={null} onChange={(next) => setKind(next as Kind)}
          options={(["web", "email", "section"] as Kind[]).map((k) => ({ value: k, label: text.linkKinds[k] }))}
        />
        {kind === "web" && (
          <TextField helpNotNeeded required
            label={text.linkAddress} value={address} onChange={setAddress} hint={text.linkAddressHint} placeholder="https://"
            inputProps={{ autoFocus: true }}
          />
        )}
        {kind === "email" && (
          <TextField helpNotNeeded required label={text.linkEmail} value={email} onChange={setEmail} inputProps={{ autoFocus: true, type: "email" }} />
        )}
        {kind === "section" && (
          <LabeledSelect helpNotNeeded required
            label={text.linkSection} value={anchor} onChange={setAnchor} placeholder={text.linkSectionPlaceholder}
            options={[
              ...(unknownSection ? [{ value: anchor, label: anchor }] : []),
              ...sections.map((s) => ({ value: s.anchor, label: s.label })),
            ]}
            hint={sections.length === 0 ? text.linkNoSections : text.linkSectionsHint}
          />
        )}
        {problem && <span role="alert" style={{ color: "var(--color-danger)" }}>{problem}</span>}
        {onRemove && <div><button type="button" className="btn btn-sm" onClick={onRemove}>{text.linkRemove}</button></div>}
        <FormActions
          onCancel={onClose} onSave={() => onApply(href)} saveLabel={text.linkApply}
          saveDisabled={href === "" || href === "mailto:" || problem !== null}
        />
      </div>
    </Modal>
  );
}
