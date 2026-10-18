/**
 * Module: utils/codePolicy
 *
 * Plain-language description of an organisation's project-code policy, shared by the
 * "New project" form, the project settings and Org Admin so the rule reads the same everywhere.
 */
import type { ProjectCodePolicy } from "../api/types";

const KIND_PHRASE: Record<ProjectCodePolicy["kind"], string> = {
  letters: "letters",
  digits: "digits",
  alphanumeric: "letters and digits",
};

/** `"2 to 6 letters and digits, no spaces or hyphens"`; one length when minimum equals maximum. */
export function describeCodePolicy(policy: ProjectCodePolicy): string {
  const length = policy.min_length === policy.max_length ? `${policy.min_length}` : `${policy.min_length} to ${policy.max_length}`;
  return `${length} ${KIND_PHRASE[policy.kind]}, no spaces or hyphens`;
}

/** Upper-cases a typed code the way the server stores it. */
export function normaliseProjectCode(raw: string): string {
  return raw.trim().toUpperCase();
}
