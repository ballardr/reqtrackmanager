import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { withToast } from "../testing/storybook-helpers";
import { buildAdminApi, buildTag, buildUsage, buildVocabulary } from "../testing/tagsFixtures";
import { TagAdminPanel } from "./TagAdminPanel";

/**
 * The tag administration surface (Project Admin and Org Admin): the mode, the vocabulary with its
 * per-tag tools, and one usage table per kind of record.
 */
const meta: Meta<typeof TagAdminPanel> = {
  title: "Components/TagAdminPanel",
  component: TagAdminPanel,
  decorators: [withToast()],
  args: { scope: "project" },
};
export default meta;

type Story = StoryObj<typeof TagAdminPanel>;

const body = () => within(document.body);

export const ShowsTheVocabularyAndUsageTables: Story = {
  args: { api: buildAdminApi() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const vocabulary = await canvas.findByRole("table", { name: "Tags" });
    await expect(within(vocabulary).getByText("3 records")).toBeInTheDocument();
    const requirements = canvas.getByRole("table", { name: "Where tags are used: Requirement" });
    await expect(within(requirements).getAllByRole("row")).toHaveLength(3);
    await expect(canvas.getByRole("table", { name: "Where tags are used: Pain Point" })).toBeInTheDocument();
    await expect(canvas.getByText("Archive")).toBeInTheDocument();
  },
};

export const ChangingTheModeSavesIt: Story = {
  args: { api: buildAdminApi(buildVocabulary({ has_parent: true })) },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(await canvas.findByRole("combobox", { name: "Who can add a new tag" }), "restricted");
    await waitFor(() => expect(args.api!.setMode).toHaveBeenCalledWith("restricted"));
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Who can add a new tag" }), "inherit");
    await waitFor(() => expect(args.api!.setMode).toHaveBeenCalledWith(null));
  },
};

/** A project with no parent, and an organisation, have nothing to follow, so they offer only free and restricted. */
export const ARootProjectCannotFollowAParent: Story = {
  args: { api: buildAdminApi(buildVocabulary({ own_mode: null })) },
  play: async ({ canvasElement }) => {
    const select = await within(canvasElement).findByRole("combobox", { name: "Who can add a new tag" });
    await expect(within(select).queryByRole("option", { name: "Follow the parent project" })).not.toBeInTheDocument();
    await expect(select).toHaveValue("free");
  },
};

/** An organisation has no parent to follow, so it offers only free and restricted. */
export const AnOrganisationCannotInheritTheMode: Story = {
  args: { api: buildAdminApi(buildVocabulary({ own_mode: null })), scope: "organisation" },
  play: async ({ canvasElement }) => {
    const select = await within(canvasElement).findByRole("combobox", { name: "Who can add a new tag" });
    await expect(within(select).queryByRole("option", { name: "Follow the parent project" })).not.toBeInTheDocument();
  },
};

export const AddingATag: Story = {
  args: { api: buildAdminApi() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.type(await canvas.findByRole("textbox", { name: "New tag" }), "Q4 audit");
    await userEvent.click(canvas.getByRole("button", { name: "Blue" }));
    await expect(canvas.getByRole("textbox", { name: "Colour (hex code)" })).toHaveValue("#2b6cb0");
    await userEvent.click(canvas.getByRole("button", { name: "Add tag" }));
    await waitFor(() => expect(args.api!.create).toHaveBeenCalledWith("Q4 audit", "#2b6cb0"));
    await expect(await body().findByText("Tag added.")).toBeInTheDocument();
  },
};

export const ABadNameCannotBeAdded: Story = {
  args: { api: buildAdminApi() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.type(await canvas.findByRole("textbox", { name: "New tag" }), "a,b");
    await expect(canvas.getByRole("alert")).toHaveTextContent("cannot contain a comma");
    await expect(canvas.getByRole("button", { name: "Add tag" })).toBeDisabled();
    await expect(args.api!.create).not.toHaveBeenCalled();
  },
};

export const RenamingATag: Story = {
  args: { api: buildAdminApi() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Safety" }));
    await userEvent.click(await body().findByRole("menuitem", { name: "Rename Safety" }));
    const dialog = await body().findByRole("dialog", { name: /Rename Safety/ });
    const input = within(dialog).getByRole("textbox");
    await userEvent.clear(input);
    await userEvent.type(input, "Safety case");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save name" }));
    await waitFor(() => expect(args.api!.update).toHaveBeenCalledWith("tag-safety", { name: "Safety case" }));
  },
};

/** A tag's colour is set from the row menu: a preset, a typed hex code (also `#rgb`), or none. */
export const ChangingAColour: Story = {
  args: { api: buildAdminApi() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Release 2" }));
    await userEvent.click(await body().findByRole("menuitem", { name: "Change colour of Release 2" }));
    const dialog = await body().findByRole("dialog", { name: /Change colour of Release 2/ });
    const hex = within(dialog).getByRole("textbox", { name: "Colour of Release 2 (hex code)" });
    await userEvent.clear(hex);
    await userEvent.type(hex, "#0a8");
    await expect(hex).not.toHaveAttribute("aria-invalid");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save colour" }));
    await waitFor(() => expect(args.api!.update).toHaveBeenCalledWith("tag-release-2", { colour: "#00aa88" }));

    await userEvent.click(canvas.getByRole("button", { name: "Safety" }));
    await userEvent.click(await body().findByRole("menuitem", { name: "Change colour of Safety" }));
    const second = await body().findByRole("dialog", { name: /Change colour of Safety/ });
    await userEvent.click(within(second).getByRole("button", { name: "No colour" }));
    await userEvent.click(within(second).getByRole("button", { name: "Save colour" }));
    await waitFor(() => expect(args.api!.update).toHaveBeenCalledWith("tag-safety", { clear_colour: true }));
  },
};

/** Text that is not a colour is flagged and never sent; the save keeps the last good colour. */
export const ABadHexCodeIsFlaggedAndNotSent: Story = {
  args: { api: buildAdminApi() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Release 2" }));
    await userEvent.click(await body().findByRole("menuitem", { name: "Change colour of Release 2" }));
    const dialog = await body().findByRole("dialog", { name: /Change colour of Release 2/ });
    const hex = within(dialog).getByRole("textbox", { name: "Colour of Release 2 (hex code)" });
    await userEvent.clear(hex);
    await userEvent.type(hex, "red;background:url(x)".slice(0, 7));
    await expect(hex).toHaveAttribute("aria-invalid", "true");
    await expect(within(dialog).getByRole("alert")).toHaveTextContent("Enter a colour as #rgb or #rrggbb.");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save colour" }));
    // Release 2 had no colour, so nothing but "no colour" can be sent.
    await waitFor(() => expect(args.api!.update).toHaveBeenCalledWith("tag-release-2", { clear_colour: true }));
  },
};

export const MergingATagNamesWhatMoves: Story = {
  args: { api: buildAdminApi() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Release 2" }));
    await userEvent.click(await body().findByRole("menuitem", { name: "Merge Release 2 into another tag" }));
    const dialog = await body().findByRole("dialog", { name: /Merge "Release 2"/ });
    await expect(within(dialog).getByText(/Every record tagged "Release 2" \(1\) gets the other tag instead/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Merge" }));
    await waitFor(() => expect(args.api!.merge).toHaveBeenCalledWith("tag-release-2", "tag-safety"));
    await expect(await body().findByText("Merged. 2 records moved.")).toBeInTheDocument();
  },
};

/** Deleting is the strict tier: type the tag's name, and the dialog says how many records lose it. */
export const DeletingATagNeedsItsNameTyped: Story = {
  args: { api: buildAdminApi() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Safety" }));
    await userEvent.click(await body().findByRole("menuitem", { name: "Delete Safety" }));
    const dialog = await body().findByRole("dialog", { name: /Delete tag "Safety"\?/ });
    await expect(within(dialog).getByText(/removed from 3 records/)).toBeInTheDocument();
    const confirm = within(dialog).getByRole("button", { name: "Delete tag" });
    await expect(confirm).toBeDisabled();
    await userEvent.type(within(dialog).getByRole("textbox"), "Safety");
    await userEvent.click(confirm);
    await waitFor(() => expect(args.api!.remove).toHaveBeenCalledWith("tag-safety"));
    await expect(await body().findByText("Tag deleted. It was removed from 3 records.")).toBeInTheDocument();
  },
};

/** Reclassify previews the count before anything is written, and applies only after the preview. */
export const ReclassifyingPreviewsThenApplies: Story = {
  args: { api: buildAdminApi() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Safety" }));
    await userEvent.click(await body().findByRole("menuitem", { name: "Reclassify records tagged Safety" }));
    const dialog = await body().findByRole("dialog", { name: /Reclassify records tagged "Safety"/ });
    await userEvent.click(within(dialog).getByRole("button", { name: "Add these tags" }));
    await userEvent.click(await body().findByRole("checkbox", { name: "Release 2" }));
    await userEvent.keyboard("{Escape}");
    await expect(within(dialog).getByRole("button", { name: "Apply" })).toBeDisabled();
    await userEvent.click(within(dialog).getByRole("button", { name: "Preview" }));
    await expect(await within(dialog).findByText("4 records matched: 4 tag additions and 4 removals.")).toBeInTheDocument();
    await expect(args.api!.reclassify).toHaveBeenCalledWith(expect.objectContaining({ from_tag_id: "tag-safety", dry_run: true }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Apply" }));
    await waitFor(() => expect(args.api!.reclassify).toHaveBeenCalledWith(expect.objectContaining({ dry_run: false })));
    await expect(await body().findByText("Reclassified 4 records.")).toBeInTheDocument();
  },
};

/** A usage-table row can launch reclassify for one kind of record only. */
export const ReclassifyFromAUsageRowIsLimitedToThatType: Story = {
  args: { api: buildAdminApi() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "Where tags are used: Pain Point" });
    await userEvent.click(within(table).getByRole("button", { name: /Reclassify records tagged Safety \(Pain Point\)/ }));
    const dialog = await body().findByRole("dialog", { name: /Reclassify records tagged "Safety"/ });
    await expect(within(dialog).getByRole("combobox", { name: "Only these record types" })).toHaveValue("pain_point");
  },
};

/** Ticking a tag hides it from the usage tables while the rest are reviewed; "Show all" brings it back. */
export const TickingATagHidesItFromTheUsageTables: Story = {
  args: { api: buildAdminApi() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "Where tags are used: Requirement" });
    await userEvent.click(within(table).getByRole("checkbox", { name: "Hide Safety from the tables" }));
    await expect(within(canvas.getByRole("table", { name: "Where tags are used: Requirement" })).queryByRole("checkbox", { name: "Hide Safety from the tables" })).not.toBeInTheDocument();
    await expect(canvas.getByText("1 hidden")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Show all" }));
    await expect(await canvas.findAllByRole("checkbox", { name: "Hide Safety from the tables" })).toHaveLength(2);
  },
};

export const TheFilterBoxNarrowsATable: Story = {
  args: { api: buildAdminApi() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(await canvas.findByRole("textbox", { name: "Filter tags (Requirement)" }), "rel");
    const table = canvas.getByRole("table", { name: "Where tags are used: Requirement" });
    await expect(within(table).queryByText("Safety")).not.toBeInTheDocument();
    await expect(within(table).getByText("Release 2")).toBeInTheDocument();
  },
};

/** A child project that follows its parent's list sees it but cannot change it here. */
export const AnInheritedListIsReadOnly: Story = {
  args: {
    api: buildAdminApi(buildVocabulary({
      inherited: true, has_parent: true, own_mode: null, mode_inherited: true,
      tags: [buildTag("Safety", { editable: false, usage_count: 2 })],
    }), { usage: fn(async () => buildUsage({ unused: [] })) }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText(/belong to a parent project/)).toBeInTheDocument();
    await expect(canvas.getByText("Inherited")).toBeInTheDocument();
    await expect(canvas.getByText("Following the parent project: Anyone who can tag a record.")).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Safety" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: /^Reclassify/ })).not.toBeInTheDocument();
  },
};

export const AFailedLoadSaysSo: Story = {
  args: { api: buildAdminApi(undefined, { vocabulary: fn(async () => { throw new Error("nope"); }) }) },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByRole("alert")).toHaveTextContent("Could not load the tags.");
  },
};

export const ARefusedChangeIsToastedAndLeavesTheScreenAlone: Story = {
  args: { api: buildAdminApi(undefined, { create: fn(async () => { throw new Error("The tag 'Safety' already exists."); }) }) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(await canvas.findByRole("textbox", { name: "New tag" }), "safety");
    await userEvent.click(canvas.getByRole("button", { name: "Add tag" }));
    await expect(await body().findByText("The tag 'Safety' already exists.")).toBeInTheDocument();
    await expect(canvas.getByRole("textbox", { name: "New tag" })).toHaveValue("safety");
  },
};
