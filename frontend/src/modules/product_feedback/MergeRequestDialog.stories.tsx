import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { buildRequest, buildUnscoredRequest } from "./requestFixtures";
import { mergeCandidates } from "./mergeCandidates";
import { MergeRequestDialog } from "./MergeRequestDialog";

const duplicate = buildRequest({ id: "request-9", unique_code: "ENH-009", title: "Excel please" });
const all = [
  buildRequest(), buildUnscoredRequest(), duplicate,
  buildRequest({ id: "request-4", unique_code: "ENH-004", title: "Old", status: "delivered" }),
  buildRequest({ id: "request-5", unique_code: "ENH-005", title: "Archived", is_archived: true }),
];

const meta: Meta<typeof MergeRequestDialog> = {
  title: "Modules/ProductFeedback/MergeRequestDialog",
  component: MergeRequestDialog,
  args: { request: duplicate, candidates: mergeCandidates(duplicate, all), onMerge: fn(), onCancel: fn() },
};
export default meta;

type Story = StoryObj<typeof MergeRequestDialog>;

const dialog = () => within(within(document.body).getByRole("dialog"));

/** Only other open, unarchived requests are offered; Merge needs a choice. */
export const OffersOnlyOpenRequestsAndNeedsAChoice: Story = {
  play: async ({ args }) => {
    const d = dialog();
    const select = d.getByLabelText("Merge into");
    await expect(within(select).queryByRole("option", { name: /ENH-004/ })).not.toBeInTheDocument();
    await expect(within(select).queryByRole("option", { name: /ENH-005/ })).not.toBeInTheDocument();
    await expect(within(select).queryByRole("option", { name: /ENH-009/ })).not.toBeInTheDocument();
    await expect(d.getByRole("button", { name: "Merge" })).toBeDisabled();
    await userEvent.selectOptions(select, "request-1");
    await userEvent.type(d.getByLabelText("Note"), "Same ask");
    await userEvent.click(d.getByRole("button", { name: "Merge" }));
    await expect(args.onMerge).toHaveBeenCalledWith("request-1", "Same ask");
  },
};

export const NoCandidatesDisablesMerge: Story = {
  args: { candidates: [] },
  play: async () => {
    const d = dialog();
    await expect(d.getByLabelText("Merge into")).toBeDisabled();
    await expect(d.getByRole("button", { name: "Merge" })).toBeDisabled();
  },
};
