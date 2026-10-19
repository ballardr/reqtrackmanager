/**
 * Fixtures for the tag components' stories: builders for tags and vocabularies and fake
 * `RecordTagsApi` / `TagAdminApi` implementations whose methods are `fn()` spies, so a story can
 * assert what was called without any network.
 */
import { fn } from "storybook/test";

import type {
  RecordTags, RecordTagsApi, Tag, TagAdminApi, TagChipData, TagUsage, TagVocabulary,
} from "../api/tags";

export const TAGS_PROJECT_ID = "project-1";

/** A tag chip (name and optional colour). */
export function buildChip(name: string, colour: string | null = null): TagChipData {
  return { id: `tag-${name.toLowerCase().replace(/\s+/g, "-")}`, name, colour };
}

/** A vocabulary entry. */
export function buildTag(name: string, overrides: Partial<Tag> = {}): Tag {
  return { ...buildChip(name), usage_count: 0, editable: true, ...overrides };
}

/** A vocabulary read. */
export function buildVocabulary(overrides: Partial<TagVocabulary> = {}): TagVocabulary {
  return {
    mode: "free", mode_inherited: false, inherited: false, has_parent: false, own_mode: "free",
    tags: [buildTag("Safety", { usage_count: 3, colour: "#c53030" }), buildTag("Release 2", { usage_count: 1 })],
    ...overrides,
  };
}

/** One record's tags and picker data. */
export function buildRecordTags(overrides: Partial<RecordTags> = {}): RecordTags {
  return {
    tags: [buildChip("Safety", "#c53030")], can_edit: true, restricted: false,
    suggestions: [buildChip("Safety", "#c53030"), buildChip("Release 2"), buildChip("Security")],
    ...overrides,
  };
}

/** A fake `RecordTagsApi`; `set` echoes the names back as the record's tags. */
export function buildRecordTagsApi(
  data: RecordTags = buildRecordTags(), overrides: Partial<RecordTagsApi> = {},
): RecordTagsApi {
  return {
    get: fn(async () => data),
    set: fn(async (_p: string, _t: string, _i: string, names: string[]) => ({
      ...data, tags: names.map((name) => data.suggestions.find((s) => s.name === name) ?? buildChip(name)),
    })),
    vocabulary: fn(async () => buildVocabulary()),
    ...overrides,
  };
}

/** Usage tables for the admin stories. */
export function buildUsage(overrides: Partial<TagUsage> = {}): TagUsage {
  return {
    tables: [
      {
        artefact_type: "requirement", label: "Requirement",
        rows: [
          { tag_id: "tag-safety", name: "Safety", colour: "#c53030", count: 2, last_used: "2026-10-18T09:00:00Z" },
          { tag_id: "tag-release-2", name: "Release 2", colour: null, count: 1, last_used: "2026-10-12T09:00:00Z" },
        ],
      },
      {
        artefact_type: "pain_point", label: "Pain Point",
        rows: [{ tag_id: "tag-safety", name: "Safety", colour: "#c53030", count: 1, last_used: "2026-10-17T09:00:00Z" }],
      },
    ],
    unused: [buildChip("Archive")],
    ...overrides,
  };
}

/** A fake `TagAdminApi` whose calls resolve with plausible results. */
export function buildAdminApi(
  vocabulary: TagVocabulary = buildVocabulary(), overrides: Partial<TagAdminApi> = {},
): TagAdminApi {
  return {
    vocabulary: fn(async () => vocabulary),
    create: fn(async (name: string) => buildTag(name)),
    update: fn(async (id: string, patch: { name?: string }) => buildTag(patch.name ?? id)),
    merge: fn(async () => ({ records_moved: 2 })),
    remove: fn(async () => ({ records_untagged: 3 })),
    setMode: fn(async () => vocabulary),
    usage: fn(async () => buildUsage()),
    reclassify: fn(async (body: { dry_run: boolean }) => ({ matched: 4, added: 4, removed: 4, dry_run: body.dry_run })),
    ...overrides,
  };
}
