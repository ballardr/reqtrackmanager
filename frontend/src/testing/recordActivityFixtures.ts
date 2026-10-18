/**
 * Module: testing/recordActivityFixtures
 *
 * Builders and a fake `RecordActivityApi` for the Activity tab's stories, so each story states only
 * the entries it is about and needs no network.
 */
import { fn } from "storybook/test";

import type { RecordActivityApi, RecordActivityPage } from "../api/recordActivity";
import type { ChangeEntry } from "../api/types";

export function buildActivityEntry(overrides: Partial<ChangeEntry> = {}): ChangeEntry {
  return {
    timestamp: "2026-02-03T10:00:00Z", entity_type: "requirement", entity_id: "artefact-1", action: "updated",
    actor_id: "user-1", actor_display_name: "Alex Morgan", detail: null, ...overrides,
  };
}

/** A page body in the shape the endpoint returns. */
export function activityPage(entries: ChangeEntry[] = [], hasMore = false): RecordActivityPage {
  return { entries, has_more: hasMore };
}

/** A fake API serving `entries` in pages of the requested size. */
export function fakeRecordActivityApi(entries: ChangeEntry[] = []): RecordActivityApi {
  return {
    list: fn(async (_projectId, _type, _id, params = {}) => {
      const offset = params.offset ?? 0;
      const limit = params.limit ?? 25;
      return activityPage(entries.slice(offset, offset + limit), entries.length > offset + limit);
    }),
  };
}
