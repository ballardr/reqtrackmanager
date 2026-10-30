import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { ReportSnippetNotice } from "./ReportSnippetNotice";

/** What a snippet insertion did, shown above the designer's views, with Undo where the view has no undo of its own. */
const meta: Meta<typeof ReportSnippetNotice> = {
  title: "Components/Reports/ReportSnippetNotice",
  component: ReportSnippetNotice,
  args: {
    notice: {
      name: "Logo, top right of the cover page",
      changes: ["Inserted 1 block at nodes[0].", "Added page style Cover.", "Renamed 'Cover' to 'Cover 2' because it already existed."],
      problemsElsewhere: 0,
    },
    onDismiss: fn(),
  },
};
export default meta;

type Story = StoryObj<typeof ReportSnippetNotice>;

export const ListsEachChangeTheServerMade: Story = {
  play: async ({ canvasElement }) => {
    const notice = within(canvasElement).getByRole("status", { name: "Snippet inserted" });
    await expect(within(notice).getAllByRole("listitem")).toHaveLength(3);
    await expect(notice).toHaveTextContent("Renamed 'Cover' to 'Cover 2' because it already existed.");
    await expect(within(notice).queryByRole("button", { name: "Undo insertion" })).not.toBeInTheDocument();
  },
};

export const OffersUndoAndDismiss: Story = {
  args: { onUndo: fn() },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Undo insertion" }));
    await expect(args.onUndo).toHaveBeenCalled();
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Dismiss" }));
    await expect(args.onDismiss).toHaveBeenCalled();
  },
};

export const SaysHowManyProblemsTheLayoutAlreadyHad: Story = {
  args: { notice: { name: "Cover page", changes: ["Inserted 3 blocks at nodes[0]."], problemsElsewhere: 2 }, hint: "Ctrl+Z removes the inserted blocks." },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText(/already had 2 problems outside the snippet/)).toBeInTheDocument();
    await expect(within(canvasElement).getByText("Ctrl+Z removes the inserted blocks.")).toBeInTheDocument();
  },
};
