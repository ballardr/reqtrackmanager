/**
 * Module: components/linkOptions
 *
 * Helpers shared by the "Add a link" dialog and the create forms' quick-link field for reading the
 * link types a record can use (`ArtefactLinkTypeOption`): a stable key per type-and-direction, and
 * the relationship to preselect for a chosen record type. Kept in one place so both controls
 * default a pair to the same relationship.
 */
import type { ArtefactLinkTypeOption } from "../api/artefactLinks";

/** Identifies one usable way to link: a link type read in one direction. */
export function optionKey(option: ArtefactLinkTypeOption): string {
  return `${option.link_type_id}:${option.direction}`;
}

/**
 * The relationship to preselect for a record type: the symmetric "Related to" when offered, else the first.
 *
 * @param options The link types usable from the page record.
 * @param otherType The artefact type at the other end.
 * @returns The option's key, or a key with an empty link type id when none reaches `otherType`.
 */
export function defaultOptionKey(options: ArtefactLinkTypeOption[], otherType: string): string {
  const usable = options.filter((o) => o.other_types.some((t) => t.type === otherType));
  const related = usable.find((o) => o.forward_name === "Related to" && o.reverse_name === "Related to");
  return optionKey(related ?? usable[0] ?? ({ link_type_id: "", direction: "outgoing" } as ArtefactLinkTypeOption));
}
