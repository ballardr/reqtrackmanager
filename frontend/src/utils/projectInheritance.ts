/**
 * Module: utils/projectInheritance
 *
 * Rules about a project's access inheritance mode that more than one screen applies.
 */
import type { ProjectRoleInheritanceMode } from "../api/types";

/**
 * Modes that can convey manager or administrator control (unlike a member-only mode, which caps at the
 * baseline member role), so choosing one asks for confirmation first.
 */
export const MODES_NEEDING_CONFIRMATION: ProjectRoleInheritanceMode[] = ["mirror_all", "mirror_role"];
