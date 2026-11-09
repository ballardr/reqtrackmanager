import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { PolicySummary } from "../api/types";
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
