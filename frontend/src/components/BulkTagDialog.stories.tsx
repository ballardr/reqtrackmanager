import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { buildAdminApi, buildTag, buildVocabulary } from "../testing/tagsFixtures";
import { BulkTagDialog } from "./BulkTagDialog";

/**
 * Tags the records selected in a list: add and remove tags, preview the count, then apply. It uses the
 * reclassify call in its `records` form, so the server applies the same rules as for one record.
 */
const meta: Meta<typeof BulkTagDialog> = {
  title: "Components/BulkTagDialog",
  component: BulkTagDialog,
  args: {
    artefactType: "requirement", ids: ["req-1", "req-2", "req-3"], title: "Tag 3 selected requirements",
    onClose: fn(), onApplied: fn(),
  },
};
export default meta;

type Story = StoryObj<typeof BulkTagDialog>;

const body = () => within(document.body);

export const PreviewsThenApplies: Story = {
  args: { api: buildAdminApi() },
  play: async ({ args }) => {
    const dialog = await body().findByRole("dialog", { name: "Tag 3 selected requirements" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Add these tags" }));
    await userEvent.click(await body().findByRole("checkbox", { name: "Release 2" }));
    await userEvent.keyboard("{Escape}");
    await expect(within(dialog).getByRole("button", { name: "Apply" })).toBeDisabled();
    await userEvent.click(within(dialog).getByRole("button", { name: "Preview" }));
    await expect(await within(dialog).findByText("4 records matched: 4 tag additions and 4 removals.")).toBeInTheDocument();
    await expect(args.api!.reclassify).toHaveBeenCalledWith({
      records: [
        { artefact_type: "requirement", artefact_id: "req-1" },
        { artefact_type: "requirement", artefact_id: "req-2" },
        { artefact_type: "requirement", artefact_id: "req-3" },
      ],
      add: ["tag-release-2"], remove: [], dry_run: true,
    });
    await userEvent.click(within(dialog).getByRole("button", { name: "Apply" }));
    await waitFor(() => expect(args.onApplied).toHaveBeenCalledWith(expect.objectContaining({ dry_run: false })));
  },
};

/** A project that follows its parent's list has no tags of its own to pick here, and the dialog says why. */
export const AnInheritedListOffersNothingToPick: Story = {
  args: {
    api: buildAdminApi(buildVocabulary({ inherited: true, tags: [buildTag("Safety", { editable: false })] })),
  },
  play: async () => {
    await expect(await body().findByText(/belong to a parent project/)).toBeInTheDocument();
    await userEvent.click(body().getByRole("button", { name: "Add these tags" }));
    await expect(body().queryByRole("checkbox", { name: "Safety" })).not.toBeInTheDocument();
  },
};

/** A refusal (for example no permission for a record) is shown and nothing is applied. */
export const ARefusalIsShown: Story = {
  args: {
    api: buildAdminApi(undefined, { reclassify: fn(async () => { throw new Error("You do not have permission to tag requirement records."); }) }),
  },
  play: async ({ args }) => {
    const dialog = await body().findByRole("dialog", { name: "Tag 3 selected requirements" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Remove these tags" }));
    await userEvent.click(await body().findByRole("checkbox", { name: "Safety" }));
    await userEvent.keyboard("{Escape}");
    await userEvent.click(within(dialog).getByRole("button", { name: "Preview" }));
    await expect(await within(dialog).findByText(/You do not have permission/)).toBeInTheDocument();
    await expect(args.onApplied).not.toHaveBeenCalled();
  },
};
