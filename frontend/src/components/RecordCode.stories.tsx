import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { ProjectContext } from "../context/ProjectContextValue";
import { buildUser, withAuth } from "../testing/storybook-helpers";
import { RecordCode } from "./RecordCode";

const meta: Meta<typeof RecordCode> = {
  title: "Components/RecordCode",
  component: RecordCode,
  args: { code: "REQ-001" },
};
export default meta;
type Story = StoryObj<typeof RecordCode>;

function inProject(enforced: boolean) {
  return (Story: () => React.ReactElement) => (
    <ProjectContext.Provider value={{ terminology: {}, projectCode: "ACME", enforceCodeEverywhere: enforced }}>
      <Story />
    </ProjectContext.Provider>
  );
}

/** Not enforced and no preference stored: the default is to show the project code. */
export const DefaultShowsProjectCode: Story = {
  decorators: [inProject(false), withAuth(buildUser())],
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("ACME-REQ-001")).toBeInTheDocument();
  },
};

/** Not enforced, and the viewer turned the preference off: the bare code inside the project. */
export const PreferenceOffShowsBareCode: Story = {
  decorators: [inProject(false), withAuth(buildUser({ ui_preferences: { show_project_code: false } }))],
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("REQ-001")).toBeInTheDocument();
  },
};

/** The organisation enforces the project code: a viewer's "off" preference is overridden. */
export const EnforcedOverridesPreference: Story = {
  decorators: [inProject(true), withAuth(buildUser({ ui_preferences: { show_project_code: false } }))],
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("ACME-REQ-001")).toBeInTheDocument();
  },
};

/** A record owned by another project is always qualified with that project's code, preference off or not. */
export const OtherProjectAlwaysQualified: Story = {
  args: { ownerProjectCode: "BETA" },
  decorators: [inProject(false), withAuth(buildUser({ ui_preferences: { show_project_code: false } }))],
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("BETA-REQ-001")).toBeInTheDocument();
  },
};

/** Outside any project (no project code known) the code is shown as stored. */
export const OutsideAProject: Story = {
  decorators: [withAuth(buildUser())],
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("REQ-001")).toBeInTheDocument();
  },
};
