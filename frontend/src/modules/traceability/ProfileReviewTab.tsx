/**
 * Module: modules/traceability/ProfileReviewTab
 *
 * The Review tab of a governance profile: for each record type with a review schedule, the interval, reminder lead and
 * default owner the profile gives the projects it applies to.
 *
 * Responsibilities:
 * - Read the profile's review policy and show one `PolicyTable` row per record type.
 * - Edit one record type's settings in `ReviewSettingsModal` and refresh from the response; a type whose settings are all
 *   empty has no policy row, which is how a setting is removed.
 *
 * Dependencies: `profileApi`, `PolicyTable`, `ReviewSettingsModal`.
 */
import { useCallback, useState } from "react";

import { LoadFailed } from "../../components/LoadFailed";
import { Spinner } from "../../components/Spinner";
import { PrincipalBadge } from "../../components/PrincipalBadge";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { profileApi } from "./api";
import { reviewValuesOf } from "./policyText";
import { PolicyTable } from "./PolicyTable";
import { ReviewSettingsModal } from "./ReviewSettingsModal";
import type { ProfileReview, ProfileReviewType, ReviewSettingsValues } from "./types";
import { useOrgMembers } from "./useOrgMembers";

/**
 * @param orgId The organisation that owns the profile.
 * @param profileId The profile whose review policy is shown.
 */
export function ProfileReviewTab({ orgId, profileId }: { orgId: string; profileId: string }) {
  const { showToast } = useToast();
  const [data, setData] = useState<ProfileReview | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [editing, setEditing] = useState<ProfileReviewType | null>(null);
  const orgUsers = useOrgMembers(orgId);

  const load = useCallback(async () => {
    try {
      setData(await profileApi.review(orgId, profileId));
      setFailure(null);
    } catch (err) {
      setFailure(toErrorMessage(err, "The review policy could not be loaded."));
    }
  }, [orgId, profileId]);
  useLoadOnChange(load, [orgId, profileId]);

  async function save(row: ProfileReviewType, values: ReviewSettingsValues | null) {
    const next = await profileApi.setReview(orgId, profileId, row.artefact_type, values ?? reviewValuesOf(null));
    setData(next);
    showToast(`Review settings for ${row.label} saved.`);
  }

  if (failure && !data) return <LoadFailed message={failure} onRetry={() => void load()} />;
  if (!data) return <Spinner />;
  const none = <span className="text-muted">Not set</span>;
  const days = (value: number | null) => (value === null ? none : value);

  return (
    <div className="stack">
      <PolicyTable
        ariaLabel="Review policy by record type" rows={data.types} emptyText="No record type has a review schedule."
        columns={[
          { key: "interval", label: "Interval (days)", width: "9rem", render: (row) => days(row.settings.interval_days), sortValue: (row) => row.settings.interval_days },
          { key: "lead", label: "Reminder lead (days)", width: "10rem", render: (row) => days(row.settings.lead_days), sortValue: (row) => row.settings.lead_days },
          {
            key: "owner", label: "Default owner", sortValue: (row) => row.settings.default_owner?.label ?? null,
            render: (row) => <div style={{ maxWidth: "16rem" }}><PrincipalBadge principal={row.settings.default_owner} placeholder="Not set" /></div>,
          },
        ]}
        rowMenu={(row) => [{ label: "Edit review settings", onSelect: () => setEditing(row) }]}
        rowMenuLabel={(row) => `Actions for ${row.label}`}
      />
      {editing && (
        <ReviewSettingsModal
          typeLabel={editing.label} initial={reviewValuesOf(editing.settings)} ownerDisplay={editing.settings.default_owner}
          orgUsers={orgUsers} organizationId={orgId} onSave={(values) => save(editing, values)} onClose={() => setEditing(null)}
        />
      )}
    </div>
  );
}
