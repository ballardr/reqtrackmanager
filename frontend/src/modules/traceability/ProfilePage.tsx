/**
 * Module: modules/traceability/ProfilePage
 *
 * One governance profile inside the organisation's Profiles section: the record header (name with a switcher to the
 * organisation's other profiles, mode, a Profiles back control) over a tab for the profile's Overview (details, reach, exemptions, effect on projects) and one tab per policy
 * part (Lifecycle, Approval, Review, Baseline).
 *
 * Responsibilities:
 * - Load the profile with its effect on projects; show a not-found message when it does not exist, never a spinner.
 * - Offer a policy tab only while its part is switched on for the organisation (the API refuses the tab's calls otherwise).
 * - Keep the active tab in the address and fall back to Overview when the address names a tab that is not offered.
 *
 * Design decisions: the tab bodies are separate components that own their data, so a tab loads only when opened. The
 * header refreshes from the Overview tab's `onChange`, so a rename or mode change shows at once.
 *
 * Dependencies: `profileApi`, `RecordHeader`, `Tabs`, the four policy tab components.
 */
import { useCallback, useId, useState } from "react";

import { api, ApiError } from "../../api/client";
import type { OrgModuleSubComponent } from "../../api/types";
import { Badge } from "../../components/Badge";
import { EntitySwitcher, type EntitySwitcherOption } from "../../components/EntitySwitcher";
import { LoadFailed } from "../../components/LoadFailed";
import { RecordHeader } from "../../components/RecordHeader";
import { Spinner } from "../../components/Spinner";
import { Tabs, tabPanelProps, type TabDef } from "../../components/Tabs";
import { useStrings } from "../../context/TerminologyContext";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { useUrlChoice } from "../../hooks/useUrlFilter";
import { profileApi } from "./api";
import { ProfileApprovalTab } from "./ProfileApprovalTab";
import { ProfileBaselineTab } from "./ProfileBaselineTab";
import { ProfileLifecycleTab } from "./ProfileLifecycleTab";
import { ProfileOverviewTab } from "./ProfileOverviewTab";
import { ProfileReviewTab } from "./ProfileReviewTab";
import { PROFILE_MODE_LABEL, PROFILE_MODE_TONE, type ProfileDetail } from "./types";

type TabKey = "overview" | "lifecycle" | "approval" | "review" | "baseline";

const TAB_KEYS: readonly TabKey[] = ["overview", "lifecycle", "approval", "review", "baseline"];

/** Every tab with its label and the sub-component that has to be on for it (none for Overview). */
const TABS: { key: TabKey; label: string; subComponent: string | null }[] = [
  { key: "overview", label: "Overview", subComponent: null },
  { key: "lifecycle", label: "Lifecycle", subComponent: "lifecycle_policies" },
  { key: "approval", label: "Approval", subComponent: "approval_policies" },
  { key: "review", label: "Review", subComponent: "review_policies" },
  { key: "baseline", label: "Baseline", subComponent: "baseline_policies" },
];

/**
 * @param orgId The organisation the profile belongs to.
 * @param profileId The profile to show.
 * @param onBack Returns to the profile list.
 */
export function ProfilePage({ orgId, profileId, onBack }: { orgId: string; profileId: string; onBack: () => void }) {
  const strings = useStrings();
  const idPrefix = useId();
  const [profile, setProfile] = useState<ProfileDetail | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "missing" | "failed">("loading");
  const [enabled, setEnabled] = useState<Set<string> | null>(null);
  const [tabParam, setTab] = useUrlChoice("tab", TAB_KEYS);

  const load = useCallback(async () => {
    try {
      const [loaded, parts] = await Promise.all([
        profileApi.get(orgId, profileId),
        api.get<OrgModuleSubComponent[]>(`/api/v1/orgs/${orgId}/modules/traceability/subcomponents`),
      ]);
      setProfile(loaded);
      setEnabled(new Set(parts.filter((p) => p.enabled).map((p) => p.subcomponent_key)));
      setState("ready");
    } catch (err) {
      setState(err instanceof ApiError && err.status === 404 ? "missing" : "failed");
    }
  }, [orgId, profileId]);
  useLoadOnChange(load, [orgId, profileId]);

  if (state === "loading") return <Spinner />;
  if (state === "missing") {
    return (
      <div className="stack">
        <RecordHeader headingLevel="h2" recordLabel="Profile" title="Profile not found" back={{ onClick: onBack, label: "Profiles" }} />
        <p role="alert">This profile does not exist or has been deleted.</p>
      </div>
    );
  }
  if (state === "failed" || !profile || !enabled) {
    return <LoadFailed message={strings.requestFailure.loadFailed("The profile")} onRetry={() => { setState("loading"); void load(); }} />;
  }

  const loadProfileOptions = async (): Promise<EntitySwitcherOption[]> =>
    (await profileApi.list(orgId)).map((p) => ({ id: p.id, label: p.name, href: `?profile=${p.id}` }));
  const offered = TABS.filter((tab) => tab.subComponent === null || enabled.has(tab.subComponent));
  const tabs: TabDef<TabKey>[] = offered.map(({ key, label }) => ({ key, label }));
  const active: TabKey = tabParam !== "" && offered.some((tab) => tab.key === tabParam) ? tabParam : "overview";

  return (
    <div className="stack">
      <RecordHeader
        headingLevel="h2" recordLabel="Profile" title={profile.name}
        badges={<Badge tone={PROFILE_MODE_TONE[profile.mode]}>{PROFILE_MODE_LABEL[profile.mode]}</Badge>}
        subtitle={profile.description || undefined}
        titleAddon={<EntitySwitcher label="Switch profile" currentId={profile.id} loadOptions={loadProfileOptions} reloadKey={profile.name} />}
        back={{ onClick: onBack, label: "Profiles" }}
      />
      <Tabs idPrefix={idPrefix} tabs={tabs} active={active} onChange={setTab} />
      <div {...tabPanelProps(idPrefix, active)} className="stack">
        {active === "overview" && <ProfileOverviewTab orgId={orgId} profile={profile} onChange={setProfile} />}
        {active === "lifecycle" && <ProfileLifecycleTab orgId={orgId} profileId={profileId} />}
        {active === "approval" && <ProfileApprovalTab orgId={orgId} profileId={profileId} />}
        {active === "review" && <ProfileReviewTab orgId={orgId} profileId={profileId} />}
        {active === "baseline" && <ProfileBaselineTab orgId={orgId} profileId={profileId} />}
      </div>
    </div>
  );
}
