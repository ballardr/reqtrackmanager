/**
 * Module: utils/policiesPath
 *
 * The addresses of the Policies page: `/policies` (the first policy), `/policies/<policyId>` and
 * `/policies/licences/<section>` (a section of the built-in Licences group).
 *
 * Responsibilities: name the licence sections once and read what an address selects. Pure, so the signed-in route and
 * the signed-out page (which renders outside any route) resolve an address identically.
 */

/** The sections of the Licences group, in menu order. */
export const LICENCE_SECTIONS = ["product", "components", "fonts"] as const;
export type LicenceSection = (typeof LICENCE_SECTIONS)[number];

/** What the address selects: a licence section, or a policy (`id` is null when the address names none). */
export type PoliciesSelection = { kind: "licences"; section: LicenceSection } | { kind: "policy"; id: string | null };

/**
 * Reads the selection from the address.
 *
 * @param pathname The location's path (`/policies`, `/policies/<id>`, `/policies/licences/<section>`).
 * @returns The licence section or policy the address names; an unknown licence section is the first section.
 */
export function parsePoliciesPath(pathname: string): PoliciesSelection {
  const [, , first, second] = pathname.split("/");
  if (first === "licences") {
    return { kind: "licences", section: LICENCE_SECTIONS.find((s) => s === second) ?? LICENCE_SECTIONS[0] };
  }
  if (!first) return { kind: "policy", id: null };
  try {
    return { kind: "policy", id: decodeURIComponent(first) };
  } catch {
    // A malformed escape (`%E0%A4%A`) names no policy.
    return { kind: "policy", id: null };
  }
}
