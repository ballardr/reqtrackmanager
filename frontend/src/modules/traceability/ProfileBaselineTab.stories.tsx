import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withRouter, withToast } from "../../testing/storybook-helpers";
import {
  buildProfileBaseline, EMPTY_BASELINE, FIELD_OPTIONS, mockGets, ORG_ID, PROFILE_ID, profileBaselineUrl,
} from "./policyFixtures";
import { ProfileBaselineTab } from "./ProfileBaselineTab";

const PROJECTS_URL = `/api/v1/projects?organization_id=${ORG_ID}`;
const FIELDS_URL = `${profileBaselineUrl}/fields?project_id=`;
const PROJECTS = [{ id: "project-1", name: "Atlas Platform", code: "ATLAS" }, { id: "project-2", name: "Borealis", code: "BOR" }];

const meta: Meta<typeof ProfileBaselineTab> = {
  title: "Modules/Governance/ProfileBaselineTab",
  component: ProfileBaselineTab,
  args: { orgId: ORG_ID, profileId: PROFILE_ID },
  decorators: [withRouter("/"), withToast()],
  beforeEach: () => mockGets({
    [profileBaselineUrl]: buildProfileBaseline(), [PROJECTS_URL]: PROJECTS, [FIELDS_URL]: { types: FIELD_OPTIONS },
  }),
};
export default meta;

type Story = StoryObj<typeof ProfileBaselineTab>;

export const ShowsThePolicyAndOffersFieldsFromTheFirstProject: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("checkbox", { name: "Required fields" })).toBeChecked();
    await expect(await canvas.findByRole("combobox", { name: "Project for field choices" })).toHaveValue("project-1");
    await expect(canvas.getByText("Requirement · Reasoning")).toBeInTheDocument();
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(`${FIELDS_URL}project-1`));
  },
};

export const ChoosingAnotherProjectReloadsTheFieldChoices: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(await canvas.findByRole("combobox", { name: "Project for field choices" }), "project-2");
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(`${FIELDS_URL}project-2`));
  },
};

export const SaveIsUnavailableUntilSomethingChanges: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("checkbox", { name: "Required fields" });
    await expect(canvas.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.click(canvas.getByRole("checkbox", { name: "Required approvals" }));
    await expect(canvas.getByRole("button", { name: "Save" })).toBeEnabled();
  },
};

export const SavingSendsTheWholePolicy: Story = {
  play: async ({ canvasElement }) => {
    const saved = buildProfileBaseline({ ...EMPTY_BASELINE, checks: ["traceability:required_approvals"] });
    spyOn(api, "put").mockResolvedValue(saved);
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("checkbox", { name: "Required fields" }));
    await userEvent.click(canvas.getByRole("checkbox", { name: "Required approvals" }));
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(profileBaselineUrl, {
      applies_to_stage: true, applies_to_manual: true, approval_checks: "off", notify_managers: true, checks: ["traceability:required_approvals"],
      required_fields: [{ artefact_type: "requirement", field_key: "reasoning" }],
    }));
    await expect(await within(document.body).findByText("Baseline policy saved.")).toBeInTheDocument();
  },
};

export const AFailedSaveIsShownBesideSave: Story = {
  play: async ({ canvasElement }) => {
    spyOn(api, "put").mockRejectedValue(new Error("A check key is unknown."));
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("checkbox", { name: "Required approvals" }));
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));
    await expect(await canvas.findByText("A check key is unknown.")).toBeInTheDocument();
  },
};

export const NoCheckIsAvailable: Story = {
  beforeEach: () => mockGets({
    [profileBaselineUrl]: { ...buildProfileBaseline(), check_options: [] }, [PROJECTS_URL]: PROJECTS, [FIELDS_URL]: { types: {} },
  }),
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("No baseline checks are available for this organisation.")).toBeInTheDocument();
  },
};

export const FieldsThatCannotBeLoadedAreReported: Story = {
  beforeEach: () => mockGets({
    [profileBaselineUrl]: buildProfileBaseline(), [PROJECTS_URL]: PROJECTS,
    [FIELDS_URL]: () => { throw new Error("Project not found."); },
  }),
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("The fields of this project could not be loaded.")).toBeInTheDocument();
  },
};

export const DarkTheme: Story = { ...ShowsThePolicyAndOffersFieldsFromTheFirstProject, globals: { theme: "dark" } };
