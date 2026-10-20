import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, waitFor, within } from "storybook/test";

import type { RecordActivityApi } from "../api/recordActivity";
import { buildActivityEntry, fakeRecordActivityApi } from "../testing/recordActivityFixtures";
import { buildUser, withAuth } from "../testing/storybook-helpers";
import { RecordActivity } from "./RecordActivity";

/**
 * The Activity tab of a detail page's aside: the record's own timeline, newest first, 25 at a
 * time. Link events name the record at the other end.
 */
const meta: Meta<typeof RecordActivity> = {
  title: "Components/RecordActivity",
  component: RecordActivity,
  decorators: [withAuth(buildUser())],
  args: { projectId: "project-1", artefactType: "pain_point", artefactId: "pp-1" },
};
export default meta;

type Story = StoryObj<typeof RecordActivity>;

export const ShowsTheTimelineWithoutBadgingTheRecordsOwnType: Story = {
  args: {
    api: fakeRecordActivityApi([
      buildActivityEntry({ entity_type: "pain_point", action: "archived" }),
      buildActivityEntry({ entity_type: "pain_point", action: "created", timestamp: "2026-02-01T09:00:00Z" }),
    ]),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Alex Morgan archived")).toBeInTheDocument());
    await expect(canvas.getByText("Alex Morgan created")).toBeInTheDocument();
    // Every entry is about this record, so none carries a "Pain point" badge.
    await expect(canvas.queryByText("Pain Point")).not.toBeInTheDocument();
  },
};

export const DescribesLinksByTheRecordAtTheOtherEnd: Story = {
  args: {
    api: fakeRecordActivityApi([
      buildActivityEntry({
        entity_type: "artefact_link", action: "created",
        detail: { other_label: "DEC-001 Use Postgres", other_type_label: "Decision", direction: "outgoing" },
      }),
      buildActivityEntry({
        entity_type: "artefact_link", action: "deleted",
        detail: { other_label: "REQ-004 Export", other_type_label: "Requirement", direction: "incoming" },
      }),
    ]),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() =>
      expect(canvas.getByText("Alex Morgan added a link to DEC-001 Use Postgres (Decision)")).toBeInTheDocument(),
    );
    await expect(canvas.getByText("Alex Morgan removed a link from REQ-004 Export (Requirement)")).toBeInTheDocument();
    await expect(canvas.getAllByText("Link")).toHaveLength(2);
  },
};

export const PagesWithShowMore: Story = {
  args: {
    api: fakeRecordActivityApi(
      Array.from({ length: 30 }, (_, i) =>
        buildActivityEntry({ entity_type: "pain_point", action: "updated", actor_display_name: `Person ${i + 1}` }),
      ),
    ),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Person 1 updated")).toBeInTheDocument());
    await expect(canvas.queryByText("Person 30 updated")).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Show more" }));
    await waitFor(() => expect(canvas.getByText("Person 30 updated")).toBeInTheDocument());
    await expect(canvas.queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
  },
};

export const Empty: Story = {
  args: { api: fakeRecordActivityApi([]) },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByText("No activity yet.")).toBeInTheDocument());
  },
};

export const LoadFailure: Story = {
  args: {
    api: { list: async () => { throw new Error("boom"); } } satisfies RecordActivityApi,
  },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByRole("alert")).toHaveTextContent("Could not load activity."));
  },
};
