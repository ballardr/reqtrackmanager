/**
 * Stories for `ModuleSettingsList` and `ModuleAvailabilitySelect` — the
 * shared Modules settings list Org Admin and Project Admin both render.
 */
import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { ModuleAvailabilitySelect, ModuleSettingsList } from "./ModuleSettingsList";
import { ToggleSwitch } from "./ToggleSwitch";

const meta: Meta<typeof ModuleSettingsList> = {
  title: "Components/ModuleSettingsList",
  component: ModuleSettingsList,
};
export default meta;

type Story = StoryObj<typeof ModuleSettingsList>;

const LONG_DESCRIPTION =
  "Record organisation and project Strategy — objective, current/desired future state, rationale, expected " +
  "outcomes, constraints, and measures of success — plus a standalone Future State artefact, project-scoped " +
  "Pain Points, Guiding Principles and Open Questions, each with its own review lifecycle and version history. " +
  "Open Questions follow a branching investigation lifecycle and can later be resolved by a Decision, and every " +
  "artefact can be linked to requirements, change requests and other artefacts across the organisation.";

/** Org-style list: one availability select per module, sub-components
 * collapsed until the disclosure is opened, long descriptions clamped. */
export const OrgStyle: Story = {
  args: {
    items: [
      {
        key: "compliance", name: "Compliance", version: "0.1.0",
        description: "Manage compliance standards and assess projects against them.",
        control: <ModuleAvailabilitySelect value="default_on" label="Compliance availability" onChange={fn()} />,
      },
      {
        key: "context_strategy", name: "Context & Strategy", version: "0.1.0", description: LONG_DESCRIPTION,
        control: <ModuleAvailabilitySelect value="opt_in" label="Context & Strategy availability" onChange={fn()} />,
        subSummary: "2 components · all on",
        subItems: [
          { key: "strategy", name: "Strategy", control: <ModuleAvailabilitySelect value="default_on" label="Strategy availability" onChange={fn()} /> },
          { key: "pain_point", name: "Pain Points", control: <ModuleAvailabilitySelect value="opt_in" label="Pain Points availability" onChange={fn()} /> },
        ],
      },
      {
        key: "decisions", name: "Decision Management", version: "0.1.0",
        hint: "Not available on this organisation's current plan.", muted: true,
        control: <ModuleAvailabilitySelect value="off" disabled label="Decision Management availability" onChange={fn()} />,
      },
    ],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByText("Strategy")).not.toBeInTheDocument();
    const disclosure = canvas.getByRole("button", { name: "2 components · all on" });
    await userEvent.click(disclosure);
    await expect(disclosure).toHaveAttribute("aria-expanded", "true");
    await expect(canvas.getByRole("combobox", { name: "Strategy availability" })).toHaveValue("default_on");
    await expect(canvas.getByRole("combobox", { name: "Decision Management availability" })).toBeDisabled();
    await userEvent.click(canvas.getByRole("button", { name: "More" }));
    await expect(canvas.getByRole("button", { name: "Less" })).toBeInTheDocument();
  },
};

/** Project-style list: a plain on/off switch per module. */
export const ProjectStyle: Story = {
  args: {
    items: [
      {
        key: "compliance", name: "Compliance",
        control: <ToggleSwitch checked label="Enable Compliance for this project" onChange={fn()} />,
      },
      {
        key: "decisions", name: "Decision Management", hint: "Organisation default for new projects: on",
        control: <ToggleSwitch checked={false} label="Enable Decision Management for this project" onChange={fn()} />,
      },
    ],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("switch", { name: "Enable Compliance for this project" })).toBeChecked();
    await expect(canvas.queryByRole("button", { name: /component/ })).not.toBeInTheDocument();
  },
};

/** The availability select reports the chosen value. */
export const AvailabilitySelect: StoryObj<typeof ModuleAvailabilitySelect> = {
  render: (args) => <ModuleAvailabilitySelect {...args} />,
  args: { value: "default_on", label: "Compliance availability", onChange: fn() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Compliance availability" }), "off");
    await expect(args.onChange).toHaveBeenCalledWith("off");
  },
};

export const LightTheme: Story = { ...OrgStyle, globals: { theme: "light" } };
export const DarkTheme: Story = { ...OrgStyle, globals: { theme: "dark" } };
