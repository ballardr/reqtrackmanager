/**
 * Module: modules/linkedRecordCreators
 *
 * Resolves the "create a new record" dialog of an artefact type from the module that owns it, so the shared Links
 * panel can offer "Create new" for any record type without importing a module's form. Merged from every installed
 * module's `TierAModuleDefinition.linkedRecordCreators`, like `artefactPaths.ts` merges the record pages, with the
 * relationship the page record's owner prefers (`preferredLinkPhrases`).
 */
import { installedModules } from "./registry";
import type { LinkedRecordCreator } from "./types";

/** The creator the owning module declares for `artefactType`, or `null` when none does. */
export function getLinkedRecordCreator(artefactType: string): LinkedRecordCreator | null {
  for (const module of installedModules) {
    const creator = module.linkedRecordCreators?.[artefactType];
    if (creator) return creator;
  }
  return null;
}

/** The relationship phrase the module owning `artefactType` prefers toward `otherType`, or `null` when it states none. */
export function getPreferredLinkPhrase(artefactType: string, otherType: string): string | null {
  for (const module of installedModules) {
    const phrase = module.preferredLinkPhrases?.[artefactType]?.[otherType];
    if (phrase) return phrase;
  }
  return null;
}
