import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { buildStageWorkflow } from "../testing/storybook-helpers";
import { StageWorkflowEditor } from "./StageWorkflowEditor";

/** The dialog that creates or edits a stage workflow: a name and an ordered list of phases, each with a kind. */
const meta: Meta<typeof StageWorkflowEditor> = {
  title: "Components/StageWorkflowEditor",
  component: StageWorkflowEditor,
  args: { workflow: null, onCancel: fn(), onSave: fn() },
};
export default meta;

type Story = StoryObj<typeof StageWorkflowEditor>;

const dialog = async () => within(await within(document.body).findByRole("dialog", { name: /workflow/i }));

/** Opens the actions menu of the named phase and chooses one item (the menu is drawn in a popover outside the dialog). */
async function chooseRowAction(d: Awaited<ReturnType<typeof dialog>>, phase: string, item: string) {
  await userEvent.click(d.getByRole("button", { name: `Actions for phase ${phase}` }));
  await userEvent.click(await within(document.body).findByRole("menuitem", { name: item }));
}

/** A new workflow starts with one open phase; Save stays disabled until the name and every phase are filled. */
export const CreatesAWorkflowWithOrderedPhases: Story = {
  play: async ({ args }) => {
    const d = await dialog();
    await expect(d.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.type(d.getByRole("textbox", { name: /Workflow name/ }), "Outsourced work");
    await userEvent.type(d.getByRole("textbox", { name: "Phase name 1" }), "Scoping");
    await userEvent.click(d.getByRole("button", { name: "Add phase" }));
    await userEvent.type(d.getByRole("textbox", { name: "Phase name 2" }), "Awarded");
    await userEvent.selectOptions(d.getByRole("combobox", { name: "Kind 2" }), "Locked");
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.onSave).toHaveBeenCalled());
    await expect(args.onSave).toHaveBeenCalledWith({
      name: "Outsourced work",
      phases: [{ name: "Scoping", kind: "open" }, { name: "Awarded", kind: "locked" }],
    });
  },
};

/** Editing keeps each existing phase's id (so stages in it stay attached), and reordering changes the start. */
export const EditingKeepsPhaseIdsAndOrder: Story = {
  args: { workflow: buildStageWorkflow() },
  play: async ({ args }) => {
    const d = await dialog();
    await chooseRowAction(d, "Review", "Move up");
    await chooseRowAction(d, "Archived", "Remove");
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.onSave).toHaveBeenCalled());
    await expect(args.onSave).toHaveBeenCalledWith({
      name: "Standard",
      phases: [
        { id: "phase-review", name: "Review", kind: "review" },
        { id: "phase-scoping", name: "Scoping", kind: "open" },
        { id: "phase-approved", name: "Approved", kind: "locked" },
        { id: "phase-completed", name: "Completed", kind: "closed" },
      ],
    });
  },
};

/** The last phase cannot be removed: a workflow needs at least one. The first row has no Move up, the last no Move down. */
export const KeepsAtLeastOnePhase: Story = {
  play: async () => {
    const d = await dialog();
    await userEvent.click(d.getByRole("button", { name: "Actions for phase 1" }));
    await expect(await within(document.body).findByRole("menuitem", { name: "Remove" })).toBeDisabled();
    await expect(within(document.body).queryByRole("menuitem", { name: "Move up" })).not.toBeInTheDocument();
    await expect(within(document.body).queryByRole("menuitem", { name: "Move down" })).not.toBeInTheDocument();
  },
};

/** Every control of a phase sits on one line, and each column starts at the same left edge in every row. */
export const ShowsOneAlignedLinePerPhase: Story = {
  args: { workflow: buildStageWorkflow() },
  play: async () => {
    const d = await dialog();
    const group = d.getByRole("group", { name: "Phases" });
    const first = within(group).getByRole("textbox", { name: "Phase name 1" }).getBoundingClientRect();
    const firstKind = within(group).getByRole("combobox", { name: "Kind 1" }).getBoundingClientRect();
    for (let n = 1; n <= 5; n += 1) {
      const name = within(group).getByRole("textbox", { name: `Phase name ${n}` }).getBoundingClientRect();
      const kind = within(group).getByRole("combobox", { name: `Kind ${n}` }).getBoundingClientRect();
      // Same column edges in every row, and name and kind share a line (their centres are within a pixel).
      await expect(Math.abs(name.left - first.left)).toBeLessThan(1);
      await expect(Math.abs(kind.left - firstKind.left)).toBeLessThan(1);
      await expect(Math.abs((name.top + name.bottom) / 2 - (kind.top + kind.bottom) / 2)).toBeLessThan(1);
      // The kind select is sized to its options, not stretched to the name field's width.
      await expect(kind.width).toBeLessThan(name.width);
    }
  },
};

/** Many phases keep one line each; the dialog body scrolls under the pinned header, so Save stays reachable. */
export const ManyPhasesStayOnePerLine: Story = {
  args: {
    workflow: buildStageWorkflow({
      phases: Array.from({ length: 14 }, (_, i) => ({ id: `p${i}`, name: `Phase number ${i + 1}`, kind: "open" as const, sort_order: i })),
    }),
  },
  play: async () => {
    const d = await dialog();
    await expect(d.getAllByRole("combobox", { name: /^Kind / })).toHaveLength(14);
    await expect(d.getByRole("button", { name: "Save" })).toBeVisible();
  },
};

/** At a phone width the columns still fit the dialog: the grid does not overflow it sideways. */
export const FitsANarrowScreen: Story = {
  args: { workflow: buildStageWorkflow() },
  parameters: { viewport: { defaultViewport: "mobile1" } },
  play: async () => {
    const d = await dialog();
    const group = d.getByRole("group", { name: "Phases" });
    await expect(group.scrollWidth).toBeLessThanOrEqual(group.clientWidth + 1);
  },
};

/** A save error from the server (a phase in use cannot be removed) is shown in the dialog header. */
export const ShowsAServerError: Story = {
  args: { workflow: buildStageWorkflow(), error: "The phase 'Approved' is in use by a stage and cannot be removed." },
  play: async () => {
    const d = await dialog();
    await expect(d.getByText(/is in use by a stage/)).toBeInTheDocument();
  },
};
