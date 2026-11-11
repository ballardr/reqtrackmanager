import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { buildChangeEntry, withRouter } from "../testing/storybook-helpers";
import { ActivityRow } from "./ActivityRow";

const meta: Meta<typeof ActivityRow> = {
  title: "Components/ActivityRow",
  component: ActivityRow,
  decorators: [withRouter("/")],
};
export default meta;

type Story = StoryObj<typeof ActivityRow>;

/** The stacked form: the sentence (who and what), the note typed with the change and the time. */
export const WithNote: Story = {
  args: { entry: buildChangeEntry({ action: "approved", actor_display_name: "Jamie Lee", detail: { change_note: "Confirmed with the customer" } }) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Jamie Lee approved")).toBeInTheDocument();
    await expect(canvas.getByText("Confirmed with the customer")).toBeInTheDocument();
  },
};

/** A list that spans several records names the record each row is about. */
export const WithRecordLink: Story = {
  args: {
    entry: buildChangeEntry({ action: "updated" }),
    link: { to: "/projects/project-1/requirements/requirement-1", label: "SW-PERF-014 — Response time budget" },
  },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("link", { name: "SW-PERF-014 — Response time budget" })).toHaveAttribute(
      "href", "/projects/project-1/requirements/requirement-1",
    );
  },
};

/** A record's own aside leaves out the badge of its own type. */
export const WithoutTypeBadge: Story = {
  args: { entry: buildChangeEntry({ action: "created" }), showType: false },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByText("Requirement")).not.toBeInTheDocument();
  },
};
