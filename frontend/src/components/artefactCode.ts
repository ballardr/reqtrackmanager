/**
 * Module: components/artefactCode
 *
 * Splits a record's display label into its human-readable code and its title. Every item type's
 * artefact summary label is `"<PREFIX>-<nnn> <title>"` (`REQ-001 Remote diagnostics`,
 * `FND-003 Technicians skip the checklist`), the shape the shared code generator produces, so the
 * shared link lists can show the title first and the code as a small suffix instead of leading with
 * it. A label that does not start with a code (an organisation-owned or legacy record) is all title.
 */

// The generator's shape (`backend/app/code_rules.py`, `RECORD_CODE_PATTERN`): 2-5 capitals, a hyphen, and a zero-padded number
// of at least three digits (a counter past 999 simply gains digits). Deliberately narrower than "anything with a hyphen".
const CODE_PATTERN = /^([A-Z]{2,5}-\d{3,})\s+(\S[\s\S]*)$/;
// A compliance clause label, `<standard> v<version> · <clause> <title>`, whose standard can be named like a code
// ("ISO-27001 v2.0 · A.5.15 ..."): it is never split.
const CLAUSE_LABEL_PATTERN = /^\S+\s+v[\w.]+\s+·\s/;

/**
 * @param label The record's display label.
 * @returns The code (null when the label has none) and the label without it.
 */
export function splitArtefactCode(label: string): { code: string | null; title: string } {
  const match = CLAUSE_LABEL_PATTERN.test(label) ? null : CODE_PATTERN.exec(label);
  return match ? { code: match[1], title: match[2] } : { code: null, title: label };
}
