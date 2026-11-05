import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, within } from "storybook/test";

import { api } from "../../api/client";
import { requiredCaptions } from "../../testing/requiredMarkers";
import { buildUser, withStatefulAuth } from "../../testing/storybook-helpers";
import { buildRequest, buildRequester, buildRequestScheme, buildScore, ORG_ID, ORG_USERS, PROJECT_ID } from "./requestFixtures";
import { RequestFormModal } from "./RequestFormModal";

const REFERENCES_ON = [{
  module_key: "product_feedback", subcomponent_key: "external_references", name: "External references",
  effective_enabled: true, enabled: true, org_default_enabled: true, org_hard_enabled: true, has_project_override: false,
  project_override_enabled: null, default_enabled: true, default_project_enabled: true, has_org_override: false,
}];

const meta: Meta<typeof RequestFormModal> = {
  title: "Modules/ProductFeedback/RequestFormModal",
  component: RequestFormModal,
  // The edit form's collapsible Requesters section remembers whether it is open with the person's UI preferences.
  decorators: [withStatefulAuth(buildUser({ id: "user-1", display_name: "Alex Morgan" }))],
  args: {
    scopeLabel: "project", scheme: buildRequestScheme(), orgUsers: ORG_USERS, organizationId: ORG_ID, projectId: PROJECT_ID,
    onCancel: fn(), onSave: fn(),
  },
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.endsWith("/subcomponents")) return REFERENCES_ON as never;
      return (path.endsWith("/external-systems")
        ? [{ id: "system-jira", name: "Jira", display_order: 0, is_enabled: true, source: "org" }]
        : []) as never;
    });
    // The server scores the levels chosen so far: ICE needs Impact, Confidence and Ease; RICE needs Reach, Impact,
    // Confidence and Effort (a missing level means "not scored").
    spyOn(api, "post").mockImplementation(async (path: string, body?: unknown) => {
      if (!path.endsWith("/score-preview")) return {} as never;
      const levels = (body as { levels: Record<string, string | null> }).levels;
      const has = (...axes: string[]) => axes.every((axis) => Boolean(levels[axis]));
      return {
        scores: {
          ice: has("impact", "confidence", "ease") ? buildScore() : null,
          rice: has("reach", "impact", "confidence", "effort") ? buildScore({ scoring_model_key: "rice", raw: 24, normalised: 0.4, label: "Medium", tone: "info" }) : null,
        },
        derived_levels: { demand: "demand-1" }, weighted_demand: 0,
      } as never;
    });
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

/** An edit lists who has asked so far in a section that starts closed, with the field that adds more under it. */
export const EditListsCurrentRequestersInACollapsedSection: Story = {
  args: {
    initial: buildRequest(),
    currentRequesters: { requesters: [buildRequester(), buildRequester({ id: "stakeholder-2", label: "Sam Rivera", from_merge: true })], total: 5 },
  },
  play: async () => {
    const d = dialog();
    const toggle = await d.findByRole("button", { name: /Requesters/ });
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await expect(d.getByText("5 so far")).toBeInTheDocument();
    await userEvent.click(toggle);
    const list = await d.findByRole("list", { name: "Current requesters" });
    await expect(within(list).getByText("Sam Rivera")).toBeInTheDocument();
    await expect(within(list).getByText(/merged duplicate/)).toBeInTheDocument();
    await expect(d.getByText("Showing 2 of 5; the Demand card lists them all.")).toBeInTheDocument();
  },
};

/** The scores of the chosen levels are shown under the pickers as they are chosen, and a model says what it still needs. */
export const ScoresAppearAsLevelsAreChosen: Story = {
  play: async () => {
    const d = dialog();
    const scores = await d.findByRole("region", { name: "Scores" });
    // A model still lacking levels reads "Not scored"; its tooltip says what it needs.
    await expect(await within(scores).findByLabelText("Not scored. Needs Impact, Confidence, Ease to be scored")).toBeInTheDocument();
    await expect(within(scores).getByLabelText("Not scored. Needs Reach, Impact, Confidence, Effort to be scored")).toBeInTheDocument();
    await expect(within(scores).queryByText(/needs/i)).not.toBeInTheDocument();
    for (const [axis, level] of [["Impact", "impact-4"], ["Confidence", "conf-4"], ["Ease", "ease-4"]] as const) {
      await userEvent.selectOptions(d.getByLabelText(axis), level);
    }
    await expect(await within(scores).findByText("High · 48")).toBeInTheDocument();
    await expect(within(scores).queryByTitle(/Needs Impact/)).not.toBeInTheDocument();
    await expect(within(scores).getByLabelText("Not scored. Needs Reach, Effort to be scored")).toBeInTheDocument();
  },
};

/** An edit asks for the scores of the request itself, so its weighted demand feeds the derived Demand criterion. */
export const EditPreviewNamesTheRequest: Story = {
  args: { initial: buildRequest() },
  play: async () => {
    const scores = await dialog().findByRole("region", { name: "Scores" });
    await within(scores).findByText("High · 48");
    const calls = (api.post as unknown as { mock: { calls: [string, { request_id: string | null }][] } }).mock.calls;
    await expect(calls.some(([path, body]) => path.endsWith("/score-preview") && body.request_id === "request-1")).toBe(true);
  },
};

/** The inbox previews under the organisation's own models. */
export const InboxPreviewUsesTheOrganisationEndpoint: Story = {
  args: { scopeLabel: "organisation inbox", projectId: undefined },
  play: async () => {
    await within(await dialog().findByRole("region", { name: "Scores" })).findByLabelText(/Needs Impact/);
    const calls = (api.post as unknown as { mock: { calls: [string][] } }).mock.calls;
    await expect(calls.some(([path]) => path === `/api/v1/orgs/${ORG_ID}/modules/product_feedback/score-preview`)).toBe(true);
  },
};
