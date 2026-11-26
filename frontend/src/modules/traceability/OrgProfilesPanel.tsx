/**
 * Module: modules/traceability/OrgProfilesPanel
 *
 * The organisation administration section "Profiles": the organisation's governance profiles as a sortable table with a
 * New profile button, and, when the address names a profile (`?profile=<id>`), that profile's page in its place.
 *
 * Responsibilities:
 * - List each profile with its mode, the projects it reaches, its exemptions and a summary of the policy it holds.
 * - Create a profile through `ProfileFormModal` and open it; delete one after a confirmation that names what is removed.
 * - Offer a column chooser for the Reaches, Exemptions and Policy columns (Exemptions off by default).
 * - Keep the opened profile in the address, so a profile page is bookmarkable and Back returns to the list.
 *
 * Design decisions: the profile page replaces the list inside the section rather than being a route, because an
 * administration section is one page of the settings menu. Every data column is sortable (`useUrlSort`), ordered by the
 * same text the cell shows.
 *
 * Dependencies: `profileApi`, `DirectoryTable`, `ConfirmDialog`, `useMutation`.
 */
import { useCallback, useState } from "react";

import { ActionMenu } from "../../components/ActionMenu";
import { Badge } from "../../components/Badge";
import { CellText } from "../../components/CellText";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { LoadFailed } from "../../components/LoadFailed";
import { Spinner } from "../../components/Spinner";
import { cycleSort } from "../../components/sortState";
import { useStrings } from "../../context/TerminologyContext";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { useMutation } from "../../hooks/useMutation";
import { useOptionalColumns } from "../../hooks/useOptionalColumns";
import { useUrlSort, useUrlText } from "../../hooks/useUrlFilter";
import { sortRows, type SortValue } from "../../utils/sortRows";
import { profileApi } from "./api";
import { ProfileFormModal } from "./ProfileFormModal";
import { ProfilePage } from "./ProfilePage";
import { PROFILE_MODE_LABEL, PROFILE_MODE_TONE, type Profile } from "./types";

const SORT_KEYS = ["name", "mode", "reaches", "exemptions", "policy"] as const;

/** @param profile A profile. @returns The projects it reaches as the table shows them. */
function reachesText(profile: Profile): string {
  if (profile.target_kind === "all_projects") return "All projects";
  const count = profile.targets.length;
  return count === 1 ? "1 project" : `${count} projects`;
}

/** @param profile A profile. @returns A summary of the policy it holds ("Approval policy 2, Review policy 1"), or "None". */
function policyText(profile: Profile): string {
  const held = profile.contributions.filter((c) => c.count > 0).map((c) => `${c.name} ${c.count}`);
  return held.length > 0 ? held.join(", ") : "None";
}

/**
 * @param orgId The organisation whose profiles are administered.
 */
export function OrgProfilesPanel({ orgId }: { orgId: string }) {
  const strings = useStrings();
  const run = useMutation();
  const [profileId, setProfileId] = useUrlText("profile");
  const [sort, setSort] = useUrlSort(SORT_KEYS);
  const [profiles, setProfiles] = useState<Profile[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState<Profile | null>(null);

  const columns: DirectoryColumn<Profile>[] = [
    { key: "name", label: "Name", sortable: true, minWidth: "12rem", render: (row) => <CellText lines={2}>{row.name}</CellText> },
    {
      key: "mode", label: "Mode", sortable: true,
      render: (row) => <Badge tone={PROFILE_MODE_TONE[row.mode]}>{PROFILE_MODE_LABEL[row.mode]}</Badge>,
    },
    { key: "reaches", label: "Reaches", sortable: true, optional: true, render: (row) => reachesText(row) },
    { key: "exemptions", label: "Exemptions", sortable: true, optional: true, defaultHidden: true, render: (row) => row.exemptions.length },
    { key: "policy", label: "Policy", sortable: true, optional: true, render: (row) => <CellText lines={2}>{policyText(row)}</CellText> },
    {
      key: "actions", label: <span className="sr-only">Actions</span>, width: "3rem",
      render: (row) => (
        <ActionMenu triggerLabel={`Actions for ${row.name}`} items={[{ label: "Delete profile", danger: true, onSelect: () => setDeleting(row) }]} />
      ),
    },
  ];
  const shown = useOptionalColumns("governance_profiles", columns);

  const load = useCallback(async () => {
    try {
      setProfiles(await profileApi.list(orgId));
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [orgId]);
  useLoadOnChange(load, [orgId, profileId === ""]);

  if (profileId !== "") {
    return <ProfilePage orgId={orgId} profileId={profileId} onBack={() => setProfileId("")} />;
  }
  if (failed && !profiles) {
    return <LoadFailed message={strings.requestFailure.loadFailed("The profile list")} onRetry={() => { setFailed(false); void load(); }} />;
  }
  if (!profiles) return <Spinner />;

  const values: Record<string, (row: Profile) => SortValue> = {
    name: (row) => row.name,
    mode: (row) => PROFILE_MODE_LABEL[row.mode],
    reaches: reachesText,
    exemptions: (row) => row.exemptions.length,
    policy: policyText,
  };

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "flex-end" }}>
        {shown.chooser}
        <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>New profile</button>
      </div>
      <DirectoryTable
        ariaLabel="Governance profiles"
        columns={shown.columns}
        rows={sortRows(profiles, sort, values)}
        rowKey={(row) => row.id}
        sort={sort}
        onSort={(key) => setSort((current) => cycleSort(current, key as (typeof SORT_KEYS)[number]))}
        onRowClick={(row) => setProfileId(row.id)}
        emptyState={<p className="text-muted">No governance profiles yet. A profile sets the lifecycle, approval, review and baseline policy of the projects it reaches.</p>}
      />
      {creating && (
        <ProfileFormModal
          orgId={orgId} onClose={() => setCreating(false)}
          onCreated={(profile) => { setCreating(false); setProfileId(profile.id); }}
        />
      )}
      {deleting && (
        <ConfirmDialog
          title="Delete profile"
          message={`Delete ${deleting.name}? Its targets, exemptions, project choices and policy rows are removed, and the projects it reached stop following its policy. Other profiles are unaffected.`}
          confirmLabel="Delete profile"
          onCancel={() => setDeleting(null)}
          onConfirm={() => {
            const target = deleting;
            setDeleting(null);
            void run(() => profileApi.remove(orgId, target.id), { success: "Profile deleted.", failure: "Could not delete the profile." }).then((ok) => { if (ok) void load(); });
          }}
        />
      )}
    </div>
  );
}
