/**
 * Module: modules/stakeholders/createStakeholder
 *
 * Creates a Stakeholder and then puts it into the chosen groups: the
 * create endpoint takes the record's own fields only, and group membership is a
 * separate call. If that second call fails the stakeholder already exists, so
 * the failure is reported as its own message rather than rethrown, which would
 * leave the form open and invite a duplicate on retry.
 */
import { toErrorMessage } from "../../context/ToastContext";
import type { StakeholderCreateValues } from "./api";

/**
 * @param create Creates the stakeholder and resolves to its id; rejects with the create error.
 * @param setGroups Sets the new stakeholder's groups.
 * @param groupIds The groups chosen on the form.
 * @returns A warning message when the stakeholder was created but its groups could not be set, else `null`.
 */
export async function createStakeholderWithGroups(
  create: (values: StakeholderCreateValues) => Promise<{ id: string }>,
  setGroups: (stakeholderId: string, groupIds: string[]) => Promise<unknown>,
  values: StakeholderCreateValues,
  groupIds: string[],
): Promise<string | null> {
  const created = await create(values);
  if (groupIds.length === 0) return null;
  try {
    await setGroups(created.id, groupIds);
    return null;
  } catch (err) {
    return toErrorMessage(err, "The Stakeholder was created, but its groups could not be set.");
  }
}
