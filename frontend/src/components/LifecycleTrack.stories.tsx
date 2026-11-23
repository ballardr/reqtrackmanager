import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { MemoryRouter } from "react-router-dom";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { Badge } from "./Badge";
import { LifecycleTrack, type LifecycleStep } from "./LifecycleTrack";
import { RecordHeader } from "./RecordHeader";
import { expectStressStable, stressText } from "../testing/stressFixtures";
import { TextStress } from "../testing/TextStress";

const LOCKED = "Locked: use a change request to modify.";
const REQUIREMENT_STEPS: LifecycleStep[] = [
  { key: "draft", label: "Draft", description: "Being written; it can be edited directly." },
  { key: "reviewed", label: "Reviewed", description: "A reviewer has recorded an outcome; it can still be edited." },
  { key: "approved", label: "Approved", locked: true, lockedReason: LOCKED, description: "Approved by a project manager; changes need a change request." },
  { key: "completed", label: "Completed", locked: true, lockedReason: LOCKED, description: "The work is done." },
];

const meta: Meta<typeof LifecycleTrack> = {
  title: "Components/LifecycleTrack",
  component: LifecycleTrack,
  decorators: [(Story) => <MemoryRouter><div style={{ maxWidth: 760 }}><Story /></div></MemoryRouter>],
  args: { steps: REQUIREMENT_STEPS, current: "draft", promote: { to: "reviewed", onPromote: fn() } },
};
export default meta;
type Story = StoryObj<typeof LifecycleTrack>;

/** The next step is a button: it opens a popover with the Promote button, and the popover's button runs the move. */
export const NextStepOpensPromote: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("listitem", { current: "step" })).toHaveTextContent("Draft");
    await userEvent.click(canvas.getByRole("button", { name: "Next step: Reviewed" }));
    await userEvent.click(await within(document.body).findByRole("button", { name: "Promote to Reviewed" }));
    await expect(args.promote?.onPromote).toHaveBeenCalled();
  },
};

/** The track fills the width of its row. */
export const FullWidth: Story = {
  play: async ({ canvasElement }) => {
    const track = canvasElement.querySelector<HTMLElement>(".lifecycle-track")!;
    const steps = canvasElement.querySelector<HTMLElement>(".lifecycle-track__steps")!;
    await expect(Math.abs(steps.getBoundingClientRect().right - track.getBoundingClientRect().right)).toBeLessThanOrEqual(1);
  },
};

/** An earlier step is tinted, the current step is primary, and a locked step carries a padlock with the reason. */
export const ApprovedLocked: Story = {
  args: { current: "approved", promote: { to: "completed", onPromote: fn() } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("listitem", { current: "step" })).toHaveTextContent("Approved");
    await expect(canvas.getAllByRole("img", { name: LOCKED }).length).toBe(2);
  },
};

/** A person who may not promote sees a padlock on the next step, with the reason, and no control. */
export const NotPermitted: Story = {
  args: { promote: { to: "approved", blockedReason: "You do not have permission to promote this record to Approved." } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("button")).toBeNull();
    await expect(canvas.getByRole("img", { name: /Locked: use a change request to modify\.\nYou do not have permission/ })).toBeInTheDocument();
  },
};

/** The last step has no forward move. */
export const Completed: Story = {
  args: { current: "completed", promote: undefined },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("button")).toBeNull();
  },
};

/** A branch state (here Rejected) is one extra end step, highlighted, after the step the record had reached. */
export const Branch: Story = {
  args: {
    steps: [
      { key: "draft", label: "Draft" }, { key: "submitted", label: "Submitted" },
      { key: "in_review", label: "In review" }, { key: "approved", label: "Approved" },
    ],
    current: "rejected",
    offPath: { key: "rejected", label: "Rejected", after: "in_review", description: "The request was not accepted." },
    promote: undefined,
  },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("listitem", { current: "step" })).toHaveTextContent("Rejected");
  },
};

/** At a narrow width the track collapses to the current step and its position; the full track opens in a popover. */
export const Narrow: Story = {
  decorators: [(Story) => <div style={{ width: 300 }}><Story /></div>],
  args: { current: "reviewed", promote: { to: "approved", onPromote: fn() } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: /Step 2 of 4/ }));
    await waitFor(() => expect(within(document.body).getByRole("dialog")).toBeInTheDocument());
  },
};

function InHeader({ canPromote = true }: { canPromote?: boolean }) {
  const order = REQUIREMENT_STEPS.map((s) => s.key);
  const [current, setCurrent] = useState("draft");
  const next = order[order.indexOf(current) + 1];
  return (
    <RecordHeader
      recordLabel="Requirement" title="The drone shall report its battery state" code="REQ-014"
      back={{ to: "/requirements", label: "Requirements" }}
      badges={<Badge>Project</Badge>}
      onEdit={fn()}
      actions={[{ label: "Archive", danger: true, onSelect: fn() }]}
      lifecycle={{
        steps: REQUIREMENT_STEPS, current,
        promote: next ? (canPromote ? { to: next, onPromote: () => setCurrent(next) } : { to: next, blockedReason: "You do not have permission to promote this record." }) : undefined,
      }}
    />
  );
}

/** In a record header the track runs under the title and the actions, and Promote is also the first row of the actions menu. */
export const InRecordHeader: Story = {
  render: () => <InHeader />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Requirement actions" }));
    const menu = within(document.body);
    await expect(menu.getAllByRole("menuitem")[0]).toHaveTextContent("Promote to Reviewed");
    await userEvent.click(menu.getByRole("menuitem", { name: "Promote to Reviewed" }));
    await expect(canvas.getByRole("listitem", { current: "step" })).toHaveTextContent("Reviewed");
  },
};

/** A person who may not promote has no Promote row in the menu. */
export const InRecordHeaderNotPermitted: Story = {
  render: () => <InHeader canPromote={false} />,
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Requirement actions" }));
    await expect(within(document.body).queryByRole("menuitem", { name: /Promote/ })).toBeNull();
  },
};

/** Long and unbroken step labels stay inside their steps and the track keeps its shape. */
export const LongText: Story = {
  render: () => (
    <TextStress
      render={(long) => (
        <LifecycleTrack
          steps={[
            { key: "a", label: stressText(long, "Draft", "name") },
            { key: "b", label: stressText(long, "Reviewed", "word") },
            { key: "c", label: stressText(long, "Approved", "name"), locked: true, lockedReason: "Locked." },
          ]}
          current="b" promote={{ to: "c", onPromote: fn() }}
        />
      )}
    />
  ),
  play: async ({ canvasElement }) => {
    await expectStressStable(canvasElement);
  },
};
