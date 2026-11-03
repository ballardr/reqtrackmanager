import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { buildLayoutApi } from "../testing/reportLayoutFixtures";
import { ReportLayoutHistory } from "./ReportLayoutHistory";

/** The History tab of the layout designer: every saved version and a line comparison of any two. */
const meta: Meta<typeof ReportLayoutHistory> = {
  title: "Components/ReportLayoutHistory",
  component: ReportLayoutHistory,
  args: { api: buildLayoutApi(), layoutId: "layout-1", currentVersion: 2, onUseVersion: fn() },
};
export default meta;

type Story = StoryObj<typeof ReportLayoutHistory>;

export const ListsVersionsNewestFirstWithTheirNotes: Story = {
  play: async ({ canvasElement }) => {
    const table = await within(canvasElement).findByRole("table", { name: "Versions" });
    const rows = within(table).getAllByRole("row").slice(1);
    await expect(rows).toHaveLength(2);
    await expect(rows[0]).toHaveTextContent("Version 2 (current)");
    await expect(rows[0]).toHaveTextContent("Added the heading");
    await expect(rows[1]).toHaveTextContent("Version 1");
  },
};

/** The two newest versions are compared at once; added lines carry a plus and removed lines a minus, not just a colour. */
export const ComparesTheTwoNewestVersionsByDefault: Story = {
  play: async ({ canvasElement }) => {
    const diff = await within(canvasElement).findByLabelText("Changes between the two versions");
    await waitFor(() => expect(diff).toHaveTextContent("+ @each requirement sort title as req"));
    await expect(diff).toHaveTextContent("- @heading Draft");
    await expect(within(canvasElement).getByRole("combobox", { name: "Compare" })).toHaveValue("1");
    await expect(within(canvasElement).getByRole("combobox", { name: "with" })).toHaveValue("2");
  },
};

export const ComparingAVersionWithItselfSaysNothingChanged: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByLabelText("Changes between the two versions");
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Compare" }), "2");
    await expect(await canvas.findByText("These two versions are identical.")).toBeInTheDocument();
  },
};

export const AnOldVersionCanBePutInTheEditor: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Use this version as the new text (Version 1)" }));
    await waitFor(() => expect(args.onUseVersion).toHaveBeenCalledWith(1, "@layout document\n\n@heading Draft\n"));
    await expect(canvas.queryByRole("button", { name: /\(Version 2\)/ })).not.toBeInTheDocument();
  },
};

export const AReadOnlyLayoutOffersNoRestore: Story = {
  args: { onUseVersion: undefined },
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByRole("table", { name: "Versions" });
    await expect(within(canvasElement).queryByRole("button", { name: /Use this version/ })).not.toBeInTheDocument();
  },
};

export const AFailedLoadIsReported: Story = {
  args: { api: buildLayoutApi([], { versions: async () => { throw new Error("Not allowed."); } }) },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByRole("alert")).toHaveTextContent("Not allowed.");
  },
};

/** While the layout has a shared draft it is the first thing listed, apart from the published versions, with a way to discard it. */
export const ListsTheDraftAboveThePublishedVersions: Story = {
  args: {
    draft: {
      summary: { base_version: 2, revision: 3, updated_by: "user-2", updated_by_name: "Sam Rivera", updated_at: "2026-11-03T09:15:00Z" },
      onDiscard: fn(),
    },
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const row = await canvas.findByRole("note", { name: "Draft" });
    await expect(row).toHaveTextContent("Draft from Sam Rivera");
    await userEvent.click(within(row).getByRole("button", { name: "Discard draft" }));
    await expect(args.draft?.onDiscard).toHaveBeenCalled();
    await expect(await canvas.findByRole("table", { name: "Versions" })).toBeInTheDocument();
  },
};
