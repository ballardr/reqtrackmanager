import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import type { LineShape } from "../../components/graphLinePath";
import { useAttachPointVisibility } from "../../hooks/useAttachPointVisibility";
import { useSnapToGrid } from "../../hooks/useSnapToGrid";
import { buildUser, withStatefulAuth } from "../../testing/storybook-helpers";
import { DiagramSettingsButton } from "./DiagramSettingsButton";
import { StateMachineSettingsButton } from "./StateMachineSettingsButton";

/** Hosts both editors' gears on the one shared preference, as the two editors do. */
function Host() {
  const snap = useSnapToGrid();
  const points = useAttachPointVisibility();
  const [blockHops, setBlockHops] = useState(false);
  const [machineHops, setMachineHops] = useState(false);
  const [blockShape, setBlockShape] = useState<LineShape>("straight");
  const [machineShape, setMachineShape] = useState<LineShape>("straight");
  return (
    <div className="row" style={{ gap: "var(--space-4)" }}>
      <DiagramSettingsButton
        connectionDetail={false} disabled={false} onConnectionDetailChange={() => undefined} lineHops={blockHops} onLineHopsChange={setBlockHops} lineShape={blockShape} onLineShapeChange={setBlockShape} showNotes onShowNotesChange={() => undefined}
        showComments onShowCommentsChange={() => undefined} showResolved onShowResolvedChange={() => undefined}
        snapToGrid={snap.on} onSnapToGridChange={snap.setOn}
        attachPointsAlways={points.always} onAttachPointsAlwaysChange={points.setAlways}
      />
      <StateMachineSettingsButton lineHops={machineHops} disabled={false} onLineHopsChange={setMachineHops} lineShape={machineShape} onLineShapeChange={setMachineShape} snapToGrid={snap.on} onSnapToGridChange={snap.setOn} attachPointsAlways={points.always} onAttachPointsAlwaysChange={points.setAlways} />
      <span data-testid="hops">{`${blockHops}/${machineHops}`}</span>
      <span data-testid="shapes">{`${blockShape}/${machineShape}`}</span>
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
    await expect(canvas.getByRole("button", { name: "Diagram settings: line hops off, snap to grid on, attach points near the pointer" })).toHaveClass("btn-marked");
    await expect(localStorage.getItem("reqtrack.canvasSnapToGrid")).toBe("1");
  },
};

/** The switch's help says what each state does and what holding Shift does, one line each. */
export const TheHelpNamesBothStatesAndTheShiftKey: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Diagram settings: line hops off, snap to grid off, attach points near the pointer" }));
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
    await userEvent.click(canvas.getByRole("button", { name: /^Diagram settings: line hops off, snap to grid off, attach points near the pointer$/ }));
    const dialog = await within(document.body).findByRole("dialog", { name: "Diagram settings" });
    const always = within(dialog).getByRole("switch", { name: "Always show attach points" });
    await expect(always).toHaveAttribute("aria-checked", "false");
    await userEvent.click(always);
    await expect(always).toHaveAttribute("aria-checked", "true");
    await userEvent.keyboard("{Escape}");
    await expect(canvas.getByTestId("points")).toHaveTextContent("always");
    await expect(canvas.getByRole("button", { name: "Diagram settings: line hops off, snap to grid off, attach points always shown" })).toHaveClass("btn-marked");
    await expect(canvas.getByRole("button", { name: /^Diagram settings: connection detail off.*attach points always shown$/ })).toBeInTheDocument();
  },
};

/** The switch's help describes both states, one line each. */
export const TheAttachPointsHelpNamesBothStates: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: /^Diagram settings: line hops off, snap to grid off/ }));
    const dialog = await within(document.body).findByRole("dialog", { name: "Diagram settings" });
    await userEvent.click(within(dialog).getByRole("button", { name: /^Help: Always show attach points/ }));
    const tip = await within(document.body).findByRole("tooltip");
    await expect(tip).toHaveTextContent("On: every box draws its attach points all the time.");
    await expect(tip).toHaveTextContent("Off: a box draws them only while the pointer is near it");
  },
};

/** Line hops is off by default and is a switch in each editor's gear (each stores it on its own diagram); the gear is marked while it is on. */
export const LineHopsIsASwitchInEachGear: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByTestId("hops")).toHaveTextContent("false/false");
    await userEvent.click(canvas.getByRole("button", { name: /^Diagram settings: connection detail off, line hops off/ }));
    const dialog = await within(document.body).findByRole("dialog", { name: "Diagram settings" });
    const hops = within(dialog).getByRole("switch", { name: "Line hops" });
    await expect(hops).toHaveAttribute("aria-checked", "false");
    await userEvent.click(hops);
    await expect(hops).toHaveAttribute("aria-checked", "true");
    await userEvent.keyboard("{Escape}");
    await expect(canvas.getByTestId("hops")).toHaveTextContent("true/false");
    await expect(canvas.getByRole("button", { name: /^Diagram settings: connection detail off, line hops on/ })).toHaveClass("btn-marked");
    await userEvent.click(canvas.getByRole("button", { name: /^Diagram settings: line hops off, snap to grid off/ }));
    const machine = await within(document.body).findByRole("dialog", { name: "Diagram settings" });
    await userEvent.click(within(machine).getByRole("switch", { name: "Line hops" }));
    await userEvent.keyboard("{Escape}");
    await expect(canvas.getByTestId("hops")).toHaveTextContent("true/true");
  },
};

/** The switch's help describes both states, one line each, and says the arcs are in the exports. */
export const TheLineHopsHelpNamesBothStates: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: /^Diagram settings: line hops off, snap to grid off/ }));
    const dialog = await within(document.body).findByRole("dialog", { name: "Diagram settings" });
    await userEvent.click(within(dialog).getByRole("button", { name: /^Help: Line hops/ }));
    const tip = await within(document.body).findByRole("tooltip");
    await expect(tip).toHaveTextContent("On: where one line crosses another");
    await expect(tip).toHaveTextContent("Off: lines cross with no arc.");
    await expect(tip).toHaveTextContent("SVG and PNG downloads");
  },
};

/** The default line shape is a select in each gear (each stores it on its own diagram); the gear says so, and is marked, once it is not Straight. */
export const TheDefaultLineShapeIsASelectInEachGear: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByTestId("shapes")).toHaveTextContent("straight/straight");
    await userEvent.click(canvas.getByRole("button", { name: /^Diagram settings: connection detail off, line hops off/ }));
    const dialog = await within(document.body).findByRole("dialog", { name: "Diagram settings" });
    const shape = within(dialog).getByRole("combobox", { name: "Default line shape" });
    await expect(shape).toHaveValue("straight");
    await expect(within(shape).getAllByRole("option").map((o) => o.textContent)).toEqual(["Straight", "Curved", "Spline"]);
    await userEvent.selectOptions(shape, "curved");
    await expect(canvas.getByTestId("shapes")).toHaveTextContent("curved/straight");
    await userEvent.keyboard("{Escape}");
    await expect(canvas.getByRole("button", { name: /^Diagram settings: connection detail off.*, line shape curved$/ })).toHaveClass("btn-marked");
    // The state machine gear keeps its own choice.
    await userEvent.click(canvas.getByRole("button", { name: /^Diagram settings: line hops off, snap to grid off, attach points near the pointer$/ }));
    const other = await within(document.body).findByRole("dialog", { name: "Diagram settings" });
    await userEvent.selectOptions(within(other).getByRole("combobox", { name: "Default line shape" }), "spline");
    await expect(canvas.getByTestId("shapes")).toHaveTextContent("curved/spline");
  },
};

/** The select's help describes every option, one line each. */
export const TheLineShapeHelpNamesEveryOption: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: /^Diagram settings: line hops off, snap to grid off/ }));
    const dialog = await within(document.body).findByRole("dialog", { name: "Diagram settings" });
    await userEvent.click(within(dialog).getByRole("button", { name: /^Help: Default line shape/ }));
    const tip = await within(document.body).findByRole("tooltip");
    await expect(tip).toHaveTextContent("Straight: segments through the line's vertices.");
    await expect(tip).toHaveTextContent("Curved: leaves each box straight out");
    await expect(tip).toHaveTextContent("Spline: a curve through the line's vertices");
  },
};
