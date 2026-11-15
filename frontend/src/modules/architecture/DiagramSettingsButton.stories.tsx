import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, within } from "storybook/test";

import { useAttachPointVisibility } from "../../hooks/useAttachPointVisibility";
import { useSnapToGrid } from "../../hooks/useSnapToGrid";
import { buildUser, withStatefulAuth } from "../../testing/storybook-helpers";
import { DiagramSettingsButton } from "./DiagramSettingsButton";
import { StateMachineSettingsButton } from "./StateMachineSettingsButton";

/** Hosts both editors' gears on the one shared preference, as the two editors do. */
function Host() {
  const snap = useSnapToGrid();
  const points = useAttachPointVisibility();
  return (
    <div className="row" style={{ gap: "var(--space-4)" }}>
      <DiagramSettingsButton
        connectionDetail={false} disabled={false} onConnectionDetailChange={() => undefined} showNotes onShowNotesChange={() => undefined}
        showComments onShowCommentsChange={() => undefined} showResolved onShowResolvedChange={() => undefined}
        snapToGrid={snap.on} onSnapToGridChange={snap.setOn}
        attachPointsAlways={points.always} onAttachPointsAlwaysChange={points.setAlways}
      />
      <StateMachineSettingsButton snapToGrid={snap.on} onSnapToGridChange={snap.setOn} attachPointsAlways={points.always} onAttachPointsAlwaysChange={points.setAlways} />
      <span data-testid="stored">{String(snap.on)}</span>
      <span data-testid="points">{points.canvasProps.attachPointVisibility}</span>
    </div>
  );
}

const meta: Meta<typeof Host> = {
  title: "Architecture/DiagramSettingsButton",
  component: Host,
  decorators: [withStatefulAuth(buildUser({ ui_preferences: {} }))],
  beforeEach: () => { try { localStorage.removeItem("reqtrack.canvasSnapToGrid"); } catch { /* storage blocked */ } },
};
export default meta;

type Story = StoryObj<typeof Host>;

/** Snap to grid is off by default, switches on in the block diagram's gear and is the same choice in the state machine's gear. */
export const SnapToGridIsOneChoiceForBothEditors: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const blockGear = canvas.getByRole("button", { name: /^Diagram settings: connection detail off.*snap to grid off, attach points near the pointer$/ });
    await expect(blockGear).not.toHaveClass("btn-marked");
    await userEvent.click(blockGear);
    const dialog = await within(document.body).findByRole("dialog", { name: "Diagram settings" });
    const snap = within(dialog).getByRole("switch", { name: "Snap to grid" });
    await expect(snap).toHaveAttribute("aria-checked", "false");
    await userEvent.click(snap);
    await expect(snap).toHaveAttribute("aria-checked", "true");
    await userEvent.keyboard("{Escape}");
    await expect(canvas.getByTestId("stored")).toHaveTextContent("true");
    // The state machine editor's gear reads the same choice, and it is kept for the next visit.
    await expect(canvas.getByRole("button", { name: "Diagram settings: snap to grid on, attach points near the pointer" })).toHaveClass("btn-marked");
    await expect(localStorage.getItem("reqtrack.canvasSnapToGrid")).toBe("1");
  },
};

/** The switch's help says what each state does and what holding Shift does, one line each. */
export const TheHelpNamesBothStatesAndTheShiftKey: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Diagram settings: snap to grid off, attach points near the pointer" }));
    const dialog = await within(document.body).findByRole("dialog", { name: "Diagram settings" });
    await userEvent.click(within(dialog).getByRole("button", { name: /^Help: Snap to grid/ }));
    const tip = await within(document.body).findByRole("tooltip");
    await expect(tip).toHaveTextContent("On: boxes move and resize in steps of the grid");
    await expect(tip).toHaveTextContent("Off: boxes move freely.");
    await expect(tip).toHaveTextContent("Holding Shift while dragging or resizing does the opposite");
  },
};

/** Always show attach points is off by default, switches on in either gear, marks the gear and is the same choice in both. */
export const AttachPointsCanBeAlwaysShownFromEitherGear: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByTestId("points")).toHaveTextContent("near");
    await userEvent.click(canvas.getByRole("button", { name: /^Diagram settings: snap to grid off, attach points near the pointer$/ }));
    const dialog = await within(document.body).findByRole("dialog", { name: "Diagram settings" });
    const always = within(dialog).getByRole("switch", { name: "Always show attach points" });
    await expect(always).toHaveAttribute("aria-checked", "false");
    await userEvent.click(always);
    await expect(always).toHaveAttribute("aria-checked", "true");
    await userEvent.keyboard("{Escape}");
    await expect(canvas.getByTestId("points")).toHaveTextContent("always");
    await expect(canvas.getByRole("button", { name: "Diagram settings: snap to grid off, attach points always shown" })).toHaveClass("btn-marked");
    await expect(canvas.getByRole("button", { name: /^Diagram settings: connection detail off.*attach points always shown$/ })).toBeInTheDocument();
  },
};

/** The switch's help describes both states, one line each. */
export const TheAttachPointsHelpNamesBothStates: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: /^Diagram settings: snap to grid off/ }));
    const dialog = await within(document.body).findByRole("dialog", { name: "Diagram settings" });
    await userEvent.click(within(dialog).getByRole("button", { name: /^Help: Always show attach points/ }));
    const tip = await within(document.body).findByRole("tooltip");
    await expect(tip).toHaveTextContent("On: every box draws its attach points all the time.");
    await expect(tip).toHaveTextContent("Off: a box draws them only while the pointer is near it");
  },
};
