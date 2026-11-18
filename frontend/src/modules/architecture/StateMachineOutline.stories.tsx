import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { buildUser, withRouter, withStatefulAuth } from "../../testing/storybook-helpers";
import { buildStateMachineModel } from "./architectureFixtures";
import { ARCHITECTURE_HELP } from "./help";
import { layoutFromModel } from "./stateMachineModel";
import { StateMachineOutline } from "./StateMachineOutline";

const MODEL = buildStateMachineModel();

const meta: Meta<typeof StateMachineOutline> = {
  title: "Modules/Architecture/StateMachineOutline",
  component: StateMachineOutline,
  decorators: [withStatefulAuth(buildUser({ ui_preferences: {} })), withRouter("/")],
  args: { model: MODEL, layout: layoutFromModel(MODEL), selection: null, onSelect: fn() },
};
export default meta;

type Story = StoryObj<typeof StateMachineOutline>;

const tooltip = () => within(document.body).findByRole("tooltip", { hidden: true });

/** Event, condition (guard) and action each carry their help on the transition table's column headers. */
export const TransitionColumnsExplainThemselves: Story = {
  play: async ({ canvasElement }) => {
    const table = within(within(canvasElement).getByRole("table", { name: "Transitions" }));
    await userEvent.hover(table.getByRole("button", { name: "Help: Condition (guard)" }));
    await expect(await tooltip()).toHaveTextContent(ARCHITECTURE_HELP.transitionGuard);
    await expect(table.getByRole("button", { name: "Help: Event" })).toBeInTheDocument();
    await expect(table.getByRole("button", { name: "Help: Action" })).toBeInTheDocument();
    await expect(table.getByRole("button", { name: "Help: To" })).toBeInTheDocument();
  },
};

/** The States section heading says what each kind of state is, one line each. */
export const StatesHeadingListsTheKinds: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.hover(within(canvasElement).getByRole("button", { name: "Help: States" }));
    const tip = await tooltip();
    for (const kind of ["Initial state:", "Final state:", "Choice:", "composite state"]) await expect(tip).toHaveTextContent(kind);
  },
};
