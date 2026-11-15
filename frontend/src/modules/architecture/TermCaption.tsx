/**
 * Module: architecture/TermCaption
 *
 * The caption of a read-only value in a Selection card (a state's entry action, a transition's condition):
 * the term's label with its plain-language help, looked up in `ARCHITECTURE_TERMS` so the wording is the one
 * every other surface for the term shows. A term missing from the list is a programming error and throws.
 */
import { FieldCaption } from "../../components/FieldHelp";
import { ARCHITECTURE_TERMS } from "./help";

/**
 * @param term The term's label exactly as listed in `ARCHITECTURE_TERMS`.
 * @throws Error When the term is not in the list.
 */
export function TermCaption({ term }: { term: string }) {
  const found = ARCHITECTURE_TERMS.find((candidate) => candidate.label === term);
  if (!found) throw new Error(`Unknown architecture term: ${term}`);
  return <FieldCaption label={found.label} help={found.help} muted />;
}
