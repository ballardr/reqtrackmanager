Configure a project's governance and read how healthy it is.

Model: an organisation sets policy for its projects as **profiles** (named policy sets). A profile is **Enforced** (binds every project it reaches; only a named exemption lifts it), **Default** (applies unless a project opts out) or **Opt-in** (applies only where a project chooses it). A policy has four kinds: **lifecycle** (states a profile requires, no skipping steps, and the organisation stage workflow it requires), **approval** (roles that may also approve a record type), **review** (interval, reminder lead, default owner) and **baseline** (checks that run before a baseline, and optionally before approvals, and fields a record must have filled). A project's effective policy is the profiles that apply plus its own settings, and every read names where each value comes from. A policy only adds: it never removes a default approver, and no source relaxes another.

Read workflow:
1. `traceability_list_project_governance_profiles` for the profiles reaching a project; `traceability_get_project_approval_policies`, `traceability_get_project_review_policies` and `traceability_get_project_baseline_policy` for the effective policy and its sources.
2. `traceability_get_governance_health` for the project's standing: per record category the share complete (`percent`, rounded down) or the count outstanding, reviews due, and the enabled baseline checks (records checked, failing, share passing). Only the record types you may read appear, so a missing category is not zero.
3. `traceability_preview_baseline_checks` lists the failing records and checks a baseline taken now would be refused over; it writes nothing.

Health modes: `on_demand` computes for you at each call (with baseline checks enabled it is slow above `on_demand_record_limit` records, so prefer a snapshot mode there; the settings read gives the limit and `checks_enabled`); `snapshot_interval` and `snapshot_on_change` serve a stored snapshot labelled with `computed_at`. In a snapshot, the baseline check results are run as the configured check runner, or only when a person refreshes: `checks.status` says `current`, `carried_forward` (older than the snapshot; `run_by` and `run_at` say whose and when), `not_run` or `runner_unavailable`. Do not treat a carried-forward result as current.

Write workflow (needs write mode and the caller's own governance right):
- Project: `traceability_set_governance_health_settings`, `traceability_set_project_governance_profile_choice`, `traceability_set_project_approval_policy`, `traceability_set_project_review_policy`, `traceability_set_project_baseline_policy`, `traceability_refresh_governance_health`.
- Organisation: `traceability_create_governance_profile`, `traceability_update_governance_profile`, `traceability_set_governance_profile_targets`, `traceability_set_profile_lifecycle_required`, `traceability_set_profile_lifecycle_skip`, `traceability_set_profile_stage_workflow_policy`, `traceability_set_profile_approval_policy`, `traceability_set_profile_review_policy`, `traceability_set_profile_baseline_policy` and `traceability_set_governance_health_defaults`.

Rules and gotchas:
- Changing an **Enforced** profile (creating one, editing its policy or targets, or setting its mode to Enforced) changes the rules for every project it reaches. Confirm with the user before doing it.
- There is no tool to delete a profile or to add or remove an exemption: those lift a control an organisation enforces and stay a person's act in the application. There is no tool to approve, reject or finalise a baseline.
- A required stage workflow changes which workflow new stages start in and, in `restrict` mode, which workflows a project may use; existing stages are never moved. Removing the requirement is a person's act in the application.
- A baseline policy's `approval_checks` extends its checks to approvals: `manual` (a person approving one record), `automated` (a stage approved at its review deadline) or `manual_and_automated`. The check `traceability:traceability_rules` makes the project's Required traceability rules refuse; without it a Required rule is not enforced.
- A policy tool names a record type by its registered type string and the read lists the valid ones; do not invent role keys or check keys, read the `role_options` and `check_options`.
- A `roles: null`, `settings: null` or `mode: null` follows the default or the nearest ancestor project; an empty list or settings with nothing set is a choice of none and stops the ancestor applying.
- `set_governance_health_settings` replaces every field: send the ones you want to keep. A check runner must be an active user holding a role in the project.
- A sub-component that is switched off answers 404 for its tools.
