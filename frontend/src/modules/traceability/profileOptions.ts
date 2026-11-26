/**
 * Module: modules/traceability/profileOptions
 *
 * The options of the profile selects (mode and target kind), built once from the label maps so every Governance form
 * offers the same values in the same order and no form spells an enum value itself.
 */
import {
  PROFILE_MODE_LABEL, PROFILE_TARGET_KIND_LABEL, type ProfileMode, type ProfileTargetKind,
} from "./types";

/** The mode select's options, in the order of `PROFILE_MODE_LABEL`. */
export const PROFILE_MODE_OPTIONS = (Object.keys(PROFILE_MODE_LABEL) as ProfileMode[]).map((value) => ({
  value, label: PROFILE_MODE_LABEL[value],
}));

/** The target kind select's options, in the order of `PROFILE_TARGET_KIND_LABEL`. */
export const PROFILE_TARGET_KIND_OPTIONS = (Object.keys(PROFILE_TARGET_KIND_LABEL) as ProfileTargetKind[]).map((value) => ({
  value, label: PROFILE_TARGET_KIND_LABEL[value],
}));
