import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import { SEARCH_FIELDS, fakeSearchApi, buildSearchResponse } from "../testing/searchFixtures";
import { buildUser, withAuth } from "../testing/storybook-helpers";
import { SearchPreferencesPanel } from "./SearchPreferencesPanel";

const calls = fakeSearchApi(() => buildSearchResponse([]));

const meta: Meta<typeof SearchPreferencesPanel> = {
  title: "Components/SearchPreferencesPanel",
  component: SearchPreferencesPanel,
  args: { searchCalls: calls },
};
export default meta;
type Story = StoryObj<typeof SearchPreferencesPanel>;

/** With no stored choice the built-in default (ID, Title and Tags) is shown; choosing more enables Save, and Save stores the list. */
export const ChoosingFieldsSavesThem: Story = {
  decorators: [withAuth(buildUser({ ui_preferences: {} }))],
  beforeEach: () => {
    spyOn(api, "patch").mockResolvedValue({});
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Save preferences" })).toBeDisabled();
    await waitFor(() => expect(canvas.getByRole("button", { name: "Fields searched" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Fields searched" }));
    const group = within(document.body).getByRole("group", { name: "Fields searched" });
    await userEvent.click(within(group).getByRole("checkbox", { name: "Description" }));
    await userEvent.keyboard("{Escape}");
    await userEvent.click(canvas.getByRole("button", { name: "Save preferences" }));
    await waitFor(() =>
      expect(api.patch).toHaveBeenCalledWith("/api/v1/auth/me/preferences", {
        ui_preferences: { search_default_fields: ["id", "title", "tags", "description"] },
      }),
    );
  },
};

/** A server refusal (an unknown field) is shown, not swallowed. */
export const AServerRefusalIsShown: Story = {
  decorators: [withAuth(buildUser({ ui_preferences: {} }))],
  beforeEach: async () => {
    const { ApiError } = await import("../api/client");
    spyOn(api, "patch").mockRejectedValue(new ApiError(422, "Unknown search fields: gone."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Fields searched" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Fields searched" }));
    await userEvent.click(within(within(document.body).getByRole("group", { name: "Fields searched" })).getByRole("checkbox", { name: "Description" }));
    await userEvent.keyboard("{Escape}");
    await userEvent.click(canvas.getByRole("button", { name: "Save preferences" }));
    await expect(await canvas.findByRole("alert")).toHaveTextContent("Unknown search fields: gone.");
  },
};

/** A stored default that includes a field no longer offered is flagged. */
export const AStoredKeyThatIsGoneIsFlagged: Story = {
  decorators: [withAuth(buildUser({ ui_preferences: { search_default_fields: ["id", "title", "legacy"] } }))],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByText(/No longer available: legacy/);
  },
};

export const FieldsOffered: Story = {
  decorators: [withAuth(buildUser({ ui_preferences: {} }))],
  play: async () => {
    await expect(SEARCH_FIELDS.length).toBeGreaterThan(3);
  },
};

/** Comments are never a saved default, so the Preferences picker does not list them. */
export const CommentsAreNotOfferedAsADefault: Story = {
  decorators: [withAuth(buildUser({ ui_preferences: {} }))],
  args: {
    searchCalls: {
      ...fakeSearchApi(() => buildSearchResponse([])),
      fields: async () => [...SEARCH_FIELDS, { key: "comments", label: "Comments", types: ["Requirement"], default_allowed: false }],
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Fields searched" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Fields searched" }));
    const group = within(document.body).getByRole("group", { name: "Fields searched" });
    await expect(within(group).getByRole("checkbox", { name: "Description" })).toBeInTheDocument();
    await expect(within(group).queryByRole("checkbox", { name: "Comments" })).not.toBeInTheDocument();
  },
};

/** The organisation-records choice is on by default and saves as soon as it changes. */
export const OrganisationRecordsChoiceSavesImmediately: Story = {
  decorators: [withAuth(buildUser({ ui_preferences: {} }))],
  beforeEach: () => {
    spyOn(api, "patch").mockResolvedValue({});
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const box = canvas.getByRole("checkbox", { name: "Include organisation records when searching a project" });
    await expect(box).toBeChecked();
    await userEvent.click(box);
    await waitFor(() =>
      expect(api.patch).toHaveBeenCalledWith("/api/v1/auth/me/preferences", { ui_preferences: { search_include_org_records: false } }),
    );
  },
};

/** A stored "off" is shown as unchecked. */
export const OrganisationRecordsOffIsShown: Story = {
  decorators: [withAuth(buildUser({ ui_preferences: { search_include_org_records: false } }))],
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("checkbox", { name: "Include organisation records when searching a project" })).not.toBeChecked();
  },
};
