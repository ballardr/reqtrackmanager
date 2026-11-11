import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { OrgPolicySettings, OrgPolicySummary, PolicySummary } from "../api/types";
import { requiredCaptions } from "../testing/requiredMarkers";
import { buildPolicy, buildPolicySummary, withToast } from "../testing/storybook-helpers";
import { PoliciesPanel } from "./PoliciesPanel";

const UNSET_PRIVACY: PolicySummary = buildPolicySummary({ id: null, key: "privacy", title: "Privacy policy", has_unpublished_changes: false, updated_at: null });
const PUBLISHED_DATA: PolicySummary = buildPolicySummary({
  id: "data-1", key: "data", title: "Data policy", state: "published", current_version: 2, has_unpublished_changes: false, effective_from: "2026-12-01",
});
const DRAFT_ACCEPTABLE = buildPolicySummary({ id: "aup-1", title: "Acceptable use policy" });
const EDITED_PUBLISHED = buildPolicySummary({
  id: "terms-1", title: "Terms of service", state: "published", current_version: 1, has_unpublished_changes: true,
});
const REQUIRED_AGREEMENT = buildPolicySummary({
  id: "nda-1", title: "Confidentiality agreement", state: "published", current_version: 1, has_unpublished_changes: false, requires_acknowledgement: true,
});
const LIST = [UNSET_PRIVACY, PUBLISHED_DATA, DRAFT_ACCEPTABLE, EDITED_PUBLISHED];

function mockReads(list: PolicySummary[] = LIST) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === "/api/v1/system/policies") return list;
    const id = path.split("/").pop();
    const row = list.find((r) => r.id === id);
    return buildPolicy({
      ...row, id: id as string,
      versions: [{ version: 1, title: row?.title ?? "", effective_from: null, published_at: "2026-11-01T00:00:00Z", change_note: "First version" }],
    });
  });
}

/** A policy that requires acceptance is marked and offers the acceptance view; one that does not offers neither. */
export const ARequiredPolicyOffersAcceptance: Story = {
  beforeEach: () => mockReads([...LIST, REQUIRED_AGREEMENT]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("Acceptance required")).toBeInTheDocument();
    await expect(canvas.getAllByText("Acceptance required")).toHaveLength(1);
    await expect(canvas.getByRole("button", { name: "Acceptance of Confidentiality agreement" })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Acceptance of Data policy" })).not.toBeInTheDocument();
  },
};

/** The editor carries the requirement switch and sends it with the policy. */
export const TheEditorSendsTheRequirement: Story = {
  beforeEach: () => {
    mockReads();
    spyOn(api, "post").mockResolvedValue(buildPolicy());
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "New policy" }));
    const dialog = within(await within(document.body).findByRole("dialog"));
    await userEvent.type(dialog.getByRole("textbox", { name: "Title" }), "Confidentiality agreement");
    await userEvent.click(dialog.getByRole("switch", { name: "Require acceptance" }));
    await userEvent.click(await dialog.findByRole("textbox", { name: "Policy text" }));
    await userEvent.keyboard("Keep it to yourself.");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.post).toHaveBeenCalled());
    const [, payload] = (api.post as unknown as { mock: { calls: [string, { requires_acknowledgement: boolean }][] } }).mock.calls[0];
    await expect(payload.requires_acknowledgement).toBe(true);
  },
};

/** Policy administration for the server: built-in policies first, then any others. */
const meta: Meta<typeof PoliciesPanel> = {
  title: "Components/PoliciesPanel",
  component: PoliciesPanel,
  decorators: [withToast()],
  args: { scope: { kind: "server" } },
};
export default meta;

type Story = StoryObj<typeof PoliciesPanel>;

/** An unset built-in policy offers Write; a published one offers Unpublish; only a policy that is not built in can be deleted. */
export const ListsPoliciesWithStatusAndActions: Story = {
  beforeEach: () => mockReads(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("Not written")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Write Privacy policy" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Unpublish Data policy" })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Publish Data policy" })).not.toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Publish Acceptable use policy" })).toBeInTheDocument();
    await expect(canvas.getByText("Unpublished changes")).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Delete Data policy" })).not.toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Delete Acceptable use policy" })).toBeInTheDocument();
    await expect(api.get).toHaveBeenCalledWith("/api/v1/system/policies");
  },
};

/** Writing a built-in policy opens the editor with its title fixed; the title and text are the only things saved. */
export const WritingABuiltInPolicyKeepsItsTitle: Story = {
  beforeEach: () => {
    mockReads();
    spyOn(api, "post").mockResolvedValue(buildPolicy({ id: "privacy-1", key: "privacy", title: "Privacy policy" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Write Privacy policy" }));
    const dialog = within(await within(document.body).findByRole("dialog"));
    await expect(dialog.getByRole("textbox", { name: "Title" })).toHaveAttribute("readonly");
    await expect(dialog.getByRole("textbox", { name: "Title" })).toHaveValue("Privacy policy");
    await expect(requiredCaptions(document.body)).toEqual([]);
    await userEvent.click(await dialog.findByRole("textbox", { name: "Policy text" }));
    await userEvent.keyboard("We keep only what we need.");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.post).toHaveBeenCalled());
    const [url, payload] = (api.post as unknown as { mock: { calls: [string, { key: string; body: unknown }][] } }).mock.calls[0];
    await expect(url).toBe("/api/v1/system/policies");
    await expect(payload.key).toBe("privacy");
    await expect(JSON.stringify(payload.body)).toContain("We keep only what we need.");
  },
};

/** A new policy of another kind requires a title. */
export const NewPolicyRequiresATitle: Story = {
  beforeEach: () => mockReads(),
  play: async ({ canvasElement }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "New policy" }));
    const dialog = within(await within(document.body).findByRole("dialog"));
    await expect(requiredCaptions(document.body)).toEqual(["Title"]);
    await expect(dialog.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.type(dialog.getByRole("textbox", { name: "Title" }), "Terms of service");
    await expect(dialog.getByRole("button", { name: "Save" })).toBeEnabled();
  },
};

/** Publishing asks for an optional change note and posts it. */
export const PublishSendsTheChangeNote: Story = {
  beforeEach: () => {
    mockReads();
    spyOn(api, "post").mockResolvedValue(buildPolicy());
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Publish Acceptable use policy" }));
    const dialog = within(await within(document.body).findByRole("dialog"));
    await expect(requiredCaptions(document.body)).toEqual([]);
    await userEvent.type(dialog.getByRole("textbox", { name: "Change note" }), "First version");
    await userEvent.click(dialog.getByRole("button", { name: "Publish" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/v1/system/policies/aup-1/publish", { change_note: "First version" }));
  },
};

/** Unpublishing is confirmed first and keeps the versions. */
export const UnpublishIsConfirmed: Story = {
  beforeEach: () => {
    mockReads();
    spyOn(api, "post").mockResolvedValue(buildPolicy());
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Unpublish Data policy" }));
    const dialog = within(await within(document.body).findByRole("dialog"));
    await expect(dialog.getByText(/Every version is kept/)).toBeInTheDocument();
    await userEvent.click(dialog.getByRole("button", { name: "Unpublish" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/v1/system/policies/data-1/unpublish", {}));
  },
};

/** The version history lists each published version with its date and change note. */
export const HistoryListsVersions: Story = {
  beforeEach: () => mockReads(),
  play: async ({ canvasElement }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Version history: Data policy" }));
    const dialog = within(await within(document.body).findByRole("dialog"));
    await expect(await dialog.findByText("First version")).toBeInTheDocument();
  },
};

const ORG_ID = "org-1";
const ORG_BASE = `/api/v1/orgs/${ORG_ID}/policies`;
const LIMITED: OrgPolicySummary = {
  ...buildPolicySummary({ id: "access-1", title: "Access policy", state: "published", current_version: 1, has_unpublished_changes: false }),
  audience: [{ type: "org_group", id: "g1", label: "Engineering", member_count: 4, exists: true }],
};
const OPEN: OrgPolicySummary = { ...buildPolicySummary({ id: "conf-1", title: "Confidentiality agreement" }), audience: [] };
const STARTERS = ["Access policy", "Confidentiality agreement", "Acceptable use policy", "Code of conduct"];

function mockOrganisationReads(settings: OrgPolicySettings = { allow_links: false, starter_titles: STARTERS }) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === ORG_BASE) return [LIMITED, OPEN];
    if (path === `${ORG_BASE}/settings`) return settings;
    const id = path.split("/").pop();
    const row = [LIMITED, OPEN].find((r) => r.id === id);
    return { ...buildPolicy({ ...row, id: id as string }), audience: row?.audience ?? [] };
  });
}

/** An organisation has no built-in policies; each row shows who it is limited to (every member when nobody is named). */
export const OrganisationListsPoliciesWithTheirAudience: Story = {
  args: { scope: { kind: "organisation", organizationId: ORG_ID } },
  beforeEach: () => mockOrganisationReads(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("Engineering")).toBeInTheDocument();
    await expect(canvas.getByText("Every member")).toBeInTheDocument();
    await expect(canvas.queryByText("Not written")).not.toBeInTheDocument();
    await expect(api.get).toHaveBeenCalledWith(ORG_BASE);
  },
};

/** The organisation chooses whether its policies may contain links; the change applies at once. */
export const OrganisationAllowsLinksWithASwitch: Story = {
  args: { scope: { kind: "organisation", organizationId: ORG_ID } },
  beforeEach: () => {
    mockOrganisationReads();
    spyOn(api, "put").mockResolvedValue({ allow_links: true, starter_titles: STARTERS });
  },
  play: async ({ canvasElement }) => {
    const toggle = await within(canvasElement).findByRole("switch", { name: "Allow web addresses in organisation policies" });
    await expect(toggle).toHaveAttribute("aria-checked", "false");
    await userEvent.click(toggle);
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(`${ORG_BASE}/settings`, { allow_links: true }));
    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "true"));
  },
};

/** A new organisation policy offers starter titles that fill the title, and sends no key (it has no built-in policies). */
export const OrganisationNewPolicyOffersStarterTitlesAndAnAudience: Story = {
  args: { scope: { kind: "organisation", organizationId: ORG_ID } },
  beforeEach: () => {
    mockOrganisationReads();
    spyOn(api, "post").mockResolvedValue({ ...buildPolicy({ id: "new-1" }), audience: [] });
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "New policy" }));
    const dialog = within(await within(document.body).findByRole("dialog"));
    await expect(dialog.getByText("Every member of the organisation.")).toBeInTheDocument();
    await userEvent.click(dialog.getByRole("button", { name: "Confidentiality agreement" }));
    await expect(dialog.getByRole("textbox", { name: "Title" })).toHaveValue("Confidentiality agreement");
    await expect(dialog.queryByRole("button", { name: "Confidentiality agreement" })).not.toBeInTheDocument();
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.post).toHaveBeenCalled());
    const [url, payload] = (api.post as unknown as { mock: { calls: [string, { key: unknown; title: string; audience: unknown[] }][] } }).mock.calls[0];
    await expect(url).toBe(ORG_BASE);
    await expect(payload.title).toBe("Confidentiality agreement");
    await expect(payload.audience).toEqual([]);
  },
};

/** Publishing an organisation policy offers to notify the members who may read it, off unless chosen. */
export const OrganisationPublishCanNotifyMembers: Story = {
  args: { scope: { kind: "organisation", organizationId: ORG_ID } },
  beforeEach: () => {
    mockOrganisationReads();
    spyOn(api, "post").mockResolvedValue({ ...buildPolicy(), audience: [] });
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Publish Confidentiality agreement" }));
    const dialog = within(await within(document.body).findByRole("dialog"));
    const notify = dialog.getByRole("checkbox", { name: "Notify members" });
    await expect(notify).not.toBeChecked();
    await userEvent.click(notify);
    await userEvent.click(dialog.getByRole("button", { name: "Publish" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`${ORG_BASE}/conf-1/publish`, { change_note: "", notify_members: true }));
  },
};

/** Editing an existing policy shows its audience and sends it back with the text, so it is never silently dropped. */
export const OrganisationEditKeepsTheAudience: Story = {
  args: { scope: { kind: "organisation", organizationId: ORG_ID } },
  beforeEach: () => {
    mockOrganisationReads();
    spyOn(api, "put").mockResolvedValue({ ...buildPolicy(), audience: [] });
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Edit Access policy" }));
    const dialog = within(await within(document.body).findByRole("dialog"));
    await expect(dialog.getByText("Engineering")).toBeInTheDocument();
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.put).toHaveBeenCalled());
    const [, payload] = (api.put as unknown as { mock: { calls: [string, { audience: unknown[] }][] } }).mock.calls[0];
    await expect(payload.audience).toEqual([{ type: "org_group", id: "g1" }]);
  },
};
