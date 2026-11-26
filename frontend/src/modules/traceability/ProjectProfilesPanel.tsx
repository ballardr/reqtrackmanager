/**
 * Module: modules/traceability/ProjectProfilesPanel
 *
 * The Profiles section of Project Administration: every governance profile of the organisation that reaches the project,
 * what each one does for it and, where the project may choose, whether the profile applies.
 *
 * Responsibilities:
 * - Read the project's profiles (`projectGovernanceApi.profiles`) and draw them as a sortable table, Enforced first.
 * - Offer one switch per Default or Opt-in profile that saves at once with a toast: a Default profile applies until the
 *   project opts out, an Opt-in profile applies once the project opts in. Clearing the choice is a switch back to the
 *   profile's own default.
 * - Draw an Enforced profile with its outcome only, since only the organisation lifts it.
 *
 * Design decisions: the switch is unavailable (with its reason in a tooltip) for a person without the right to manage the
 * project's governance. What each mode means is in the column's `(?)` help and the tooltips, never in permanent text.
 *
 * Dependencies: `projectGovernanceApi`, `DirectoryTable`, `ToggleSwitch`, `Tooltip`.
 */
import { useCallback, useState } from "react";

import { Badge } from "../../components/Badge";
import { CellText } from "../../components/CellText";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { FieldHelp } from "../../components/FieldHelp";
import { LoadFailed } from "../../components/LoadFailed";
import { Spinner } from "../../components/Spinner";
import { cycleSort } from "../../components/sortState";
import { ToggleSwitch } from "../../components/ToggleSwitch";
import { Tooltip } from "../../components/Tooltip";
import { useStrings } from "../../context/TerminologyContext";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { useMutation } from "../../hooks/useMutation";
import { useUrlSort } from "../../hooks/useUrlFilter";
import { sortRows, type SortValue } from "../../utils/sortRows";
import { projectGovernanceApi } from "./api";
import { GOVERNANCE_HELP } from "./help";
import {
  PROFILE_MODE_DESCRIPTION,
  PROFILE_MODE_LABEL,
  PROFILE_MODE_TONE,
  PROFILE_OUTCOME_LABEL,
  PROFILE_OUTCOME_TONE,
  type ProjectProfile,
  type ProjectProfiles,
} from "./types";

const SORT_KEYS = ["name", "mode", "outcome", "choice"] as const;

/** The order of the modes in the table: Enforced, then Default, then Opt-in. */
const MODE_ORDER: Record<ProjectProfile["mode"], number> = { enforced: 0, default: 1, opt_in: 2 };

const SORT_VALUES: Record<string, (row: ProjectProfile) => SortValue> = {
  name: (row) => row.name,
  mode: (row) => MODE_ORDER[row.mode],
  outcome: (row) => PROFILE_OUTCOME_LABEL[row.outcome],
  choice: (row) => (row.can_choose ? (row.applies ? 1 : 0) : null),
};

/**
 * The choice to store when the switch is moved.
 *
 * @param profile A Default or Opt-in profile.
 * @param apply Whether the profile should apply after the change.
 * @returns `false` to opt out of a Default profile, `true` to opt in to an Opt-in profile, `null` to clear the choice.
 */
function choiceFor(profile: ProjectProfile, apply: boolean): boolean | null {
  if (profile.mode === "default") return apply ? null : false;
  return apply ? true : null;
}

/**
 * The reason the choice switch is unavailable, or `null` when it can be used.
 *
 * @param profile The profile the switch belongs to.
 * @param canManage Whether the caller may record the project's choices.
 */
function unavailableReason(profile: ProjectProfile, canManage: boolean): string | null {
  if (!profile.can_choose) return "An Enforced profile applies to every project it targets. Only the organisation can lift it.";
  if (!canManage) return "Changing a profile choice needs the right to manage this project's governance.";
  return null;
}

/**
 * @param projectId The project whose profiles are shown.
 */
export function ProjectProfilesPanel({ projectId }: { projectId: string }) {
  const strings = useStrings();
  const run = useMutation();
  const [data, setData] = useState<ProjectProfiles | null>(null);
  const [failed, setFailed] = useState(false);
  const [sort, setSort] = useUrlSort(SORT_KEYS);

  const load = useCallback(async () => {
    try {
      setData(await projectGovernanceApi.profiles(projectId));
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [projectId]);
  useLoadOnChange(load, [projectId]);

  async function choose(profile: ProjectProfile, apply: boolean) {
    let saved: ProjectProfiles | null = null;
    const ok = await run(
      async () => { saved = await projectGovernanceApi.setChoice(projectId, profile.id, choiceFor(profile, apply)); },
      { success: `The choice for ${profile.name} is saved.`, failure: `Could not save the choice for ${profile.name}.` },
    );
    if (ok && saved) setData(saved);
  }

  if (failed && !data) {
    return <LoadFailed message={strings.requestFailure.loadFailed("The governance profiles")} onRetry={() => { setFailed(false); void load(); }} />;
  }
  if (!data) return <Spinner />;

  const columns: DirectoryColumn<ProjectProfile>[] = [
    {
      key: "name", label: "Profile", sortable: true, minWidth: "12rem",
      render: (row) => <CellText lines={2} detail={row.description}>{row.name}</CellText>,
    },
    {
      key: "mode", label: "Mode", sortable: true,
      headerAction: <FieldHelp label="Mode" help={GOVERNANCE_HELP.profileMode} />,
      render: (row) => (
        <Tooltip label={PROFILE_MODE_DESCRIPTION[row.mode]} wrap>
          <Badge tone={PROFILE_MODE_TONE[row.mode]}>{PROFILE_MODE_LABEL[row.mode]}</Badge>
        </Tooltip>
      ),
    },
    {
      key: "outcome", label: "Effect on this project", sortable: true,
      render: (row) => <Badge tone={PROFILE_OUTCOME_TONE[row.outcome]}>{PROFILE_OUTCOME_LABEL[row.outcome]}</Badge>,
    },
    {
      key: "choice", label: "Applies to this project", sortable: true,
      headerAction: <FieldHelp label="Applies to this project" help={GOVERNANCE_HELP.profileChoice} />,
      render: (row) => {
        if (!row.can_choose) return <span className="text-muted">Not a choice</span>;
        const reason = unavailableReason(row, data.can_manage);
        return (
          <Tooltip label={reason ?? ""} wrap disabled={reason === null}>
            <ToggleSwitch
              label={`${row.name} applies to this project`}
              checked={row.applies}
              disabled={reason !== null}
              onChange={(next) => void choose(row, next)}
            />
          </Tooltip>
        );
      },
    },
  ];
  const rows = sortRows(data.profiles, sort, SORT_VALUES);

  return (
    <DirectoryTable
      ariaLabel="Governance profiles that reach this project"
      columns={columns}
      rows={rows}
      rowKey={(row) => row.id}
      sort={sort}
      onSort={(key) => setSort((current) => cycleSort(current, key as (typeof SORT_KEYS)[number]))}
      emptyState={<p className="text-muted">No governance profile reaches this project.</p>}
    />
  );
}
