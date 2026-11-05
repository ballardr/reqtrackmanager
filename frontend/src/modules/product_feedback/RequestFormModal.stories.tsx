import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, within } from "storybook/test";

import { api } from "../../api/client";
import { requiredCaptions } from "../../testing/requiredMarkers";
import { buildRequest, buildRequestScheme, ORG_ID, ORG_USERS, PROJECT_ID } from "./requestFixtures";
import { RequestFormModal } from "./RequestFormModal";

const meta: Meta<typeof RequestFormModal> = {
  title: "Modules/ProductFeedback/RequestFormModal",
  component: RequestFormModal,
  args: {
    scopeLabel: "project", scheme: buildRequestScheme(), orgUsers: ORG_USERS, organizationId: ORG_ID, projectId: PROJECT_ID,
    onCancel: fn(), onSave: fn(),
  },
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => (
      path.endsWith("/external-systems")
        ? [{ id: "system-jira", name: "Jira", display_order: 0, is_enabled: true, source: "org" }]
        : []
    ) as never);
  },
};
export default meta;

type Story = StoryObj<typeof RequestFormModal>;

const dialog = () => within(within(document.body).getByRole("dialog"));

/** Only the title blocks Save, and it is the only field marked required. */
export const CreateRequiresATitleAndSendsTheChosenLevels: Story = {
  play: async ({ args }) => {
    const d = dialog();
    await expect(requiredCaptions(document.body)).toEqual(["Title"]);
    await expect(d.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.type(d.getByLabelText("Request title"), "Export to Excel");
    await userEvent.selectOptions(d.getByLabelText("Impact"), "impact-4");
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Export to Excel", owner: null, levels: { impact: "impact-4" } }), [], [],
    );
  },
};

/** The derived Demand criterion names the level worked out from the requesters and can be overridden. */
export const DerivedAxisShowsTheWorkedOutLevelAndCanBeOverridden: Story = {
  args: { initial: buildRequest() },
  play: async ({ args }) => {
    const d = dialog();
    const demand = d.getByLabelText("Demand");
    await expect(within(demand).getByRole("option", { name: "Worked out: Some" })).toBeInTheDocument();
    await userEvent.selectOptions(demand, "demand-3");
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith(expect.objectContaining({ levels: expect.objectContaining({ demand: "demand-3" }) }), [], []);
  },
};

/** An edit clears a level the request had by sending null for it, and carries a change note. */
export const EditClearsALevelWithNull: Story = {
  args: { initial: buildRequest() },
  play: async ({ args }) => {
    const d = dialog();
    await userEvent.selectOptions(d.getByLabelText("Ease"), "");
    await userEvent.type(d.getByLabelText("Change note"), "Not sure about ease");
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith(
      expect.objectContaining({ levels: expect.objectContaining({ ease: null }), change_note: "Not sure about ease" }), [], [],
    );
  },
};

/** An inbox request has no links or tags (those belong to a project), so the form omits both. */
export const InboxFormOmitsQuickLinksAndTags: Story = {
  args: { scopeLabel: "organisation inbox", projectId: undefined },
  play: async () => {
    const d = dialog();
    await expect(d.queryByText(/Link to/i)).not.toBeInTheDocument();
    await expect(d.queryByLabelText("Tags")).not.toBeInTheDocument();
  },
};

/** A create takes the request's first references; an edit does not (a reference is changed on the request's page). */
export const CreateTakesReferencesButEditDoesNot: Story = {
  play: async ({ args }) => {
    const d = dialog();
    await userEvent.type(d.getByLabelText("Request title"), "Link a ticket");
    await userEvent.click(d.getByRole("button", { name: /Add a reference/ }));
    await userEvent.selectOptions(await d.findByRole("combobox", { name: "Reference 1 system" }), await d.findByRole("option", { name: "Jira" }).then((o) => (o as HTMLOptionElement).value));
    await userEvent.type(d.getByLabelText("Reference 1 key"), "PROJ-7");
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith(
      expect.objectContaining({ references: [{ system_id: "system-jira", key: "PROJ-7", url: null, role: "delivery" }] }), [], [],
    );
  },
};

export const EditHasNoReferencesField: Story = {
  args: { initial: buildRequest() },
  play: async () => {
    await expect(dialog().queryByRole("button", { name: /Add a reference/ })).not.toBeInTheDocument();
  },
};
