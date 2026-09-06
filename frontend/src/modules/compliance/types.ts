/**
 * Module: modules/compliance/types
 *
 * TypeScript mirrors of the Compliance Module's org-router Pydantic schemas
 * (backend/app/modules/compliance/schemas.py) that Phase 12's org-level
 * management UI needs — standards, versions, the requirement tree, required
 * actions, the two extensible vocabularies (action types, mapping
 * relationship types), cross-standard requirement mappings, and the
 * version-diff response (Phase 11, §27).
 *
 * Kept local to this module rather than added to `frontend/src/api/types.ts`
 * — a deliberate judgment call (see docs/compliance-module-plan.md's "Phase
 * 12 notes"): this codebase's existing convention puts every feature's
 * response shapes in the one central `api/types.ts` file, but Compliance is
 * the first genuine Tier A *installed module* (Phase 3), and keeping its own
 * (large — 15+ shapes) response-type surface inside its own module directory
 * matches that mechanism's actual intent ("an installed module directly
 * imports and uses real shared components... genuinely part of the app, not
 * a lookalike" — it doesn't say its *types* must also live in the core
 * file). The two enum/label-map pairs that render directly in the UI
 * (`ComplianceStandardVersionStatus`) still live in `api/types.ts`, per this
 * repo's binding label-map rule (CLAUDE.md, style guide Principle 12) —
 * only the plain data-shape interfaces are module-local.
 *
 * Every `id`/`*_id` field is a `string` (UUID, serialised as JSON string,
 * same convention every other frontend type in this codebase already uses).
 */

import type { ComplianceStandardVersionStatus } from "../../api/types";

export interface ComplianceStandard {
  id: string;
  organization_id: string;
  reference: string;
  name: string;
  description: string;
  issuing_organisation: string | null;
  owner_id: string;
  creator_id: string;
  is_archived: boolean;
  archived_at: string | null;
  archived_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface ComplianceStandardVersion {
  id: string;
  standard_id: string;
  version_number: number;
  version_label: string;
  status: ComplianceStandardVersionStatus;
  effective_date: string | null;
  change_note: string;
  created_by: string;
  published_at: string | null;
  published_by: string | null;
  retired_at: string | null;
  retired_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface ComplianceRequirement {
  id: string;
  standard_version_id: string;
  parent_requirement_id: string | null;
  reference: string | null;
  name: string;
  description: string;
  reasoning: string;
  sort_order: number;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface ComplianceRequiredAction {
  id: string;
  requirement_id: string;
  action_type_id: string;
  name: string;
  description: string;
  is_mandatory: boolean;
  sort_order: number;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface ComplianceActionType {
  id: string;
  organization_id: string;
  name: string;
  sort_order: number;
}

export interface ComplianceMappingRelationshipType {
  id: string;
  organization_id: string;
  name: string;
  sort_order: number;
  implies_equivalence: boolean;
}

export interface ComplianceRequirementMapping {
  id: string;
  organization_id: string;
  from_requirement_id: string;
  to_requirement_id: string;
  relationship_type_id: string;
  notes: string;
  created_by: string;
  is_archived: boolean;
  archived_at: string | null;
  archived_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface ComplianceRequirementSummary {
  id: string;
  standard_version_id: string;
  reference: string | null;
  name: string;
}

export interface AddedRequirement {
  requirement: ComplianceRequirementSummary;
}

export interface RemovedRequirement {
  requirement: ComplianceRequirementSummary;
}

export interface ModifiedRequirement {
  old_requirement: ComplianceRequirementSummary;
  new_requirement: ComplianceRequirementSummary;
  changed_fields: string[];
}

export interface ReplacedRequirement {
  old_requirement: ComplianceRequirementSummary;
  new_requirement: ComplianceRequirementSummary;
  mapping_id: string;
  relationship_type_id: string;
  implies_equivalence: boolean;
}

export interface RemappedRequirement {
  old_requirement: ComplianceRequirementSummary;
  new_requirement: ComplianceRequirementSummary;
  old_mapping_target_requirement_ids: string[];
  new_mapping_target_requirement_ids: string[];
}

export interface StandardVersionDiff {
  old_version_id: string;
  new_version_id: string;
  added: AddedRequirement[];
  removed: RemovedRequirement[];
  modified: ModifiedRequirement[];
  replaced: ReplacedRequirement[];
  re_mapped: RemappedRequirement[];
}

/** A `ComplianceRequirement` decorated with its computed tree depth and
 * children, built client-side from the backend's flat, DFS-ordered
 * `GET .../requirements` list — there is no nested-tree endpoint (see
 * `router.py::_flatten_requirements_dfs`, the algorithm `buildRequirementTree`
 * in `api.ts` mirrors). Module-local presentational shape, not a backend
 * mirror. */
export interface ComplianceRequirementNode extends ComplianceRequirement {
  depth: number;
  children: ComplianceRequirementNode[];
}
