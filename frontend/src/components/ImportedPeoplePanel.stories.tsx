import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { ImportedPeopleList } from "../api/types";
import { withToast } from "../testing/storybook-helpers";
import { ImportedPeoplePanel } from "./ImportedPeoplePanel";

const LIST: ImportedPeopleList = {
  retention_days: 90,
  people: [
    { id: "p1", display_name: "Alex Morgan", created_at: "2026-01-05T00:00:00Z", in_use: true, due_for_removal: false },
    { id: "p2", display_name: "Kim Ito", created_at: "2025-06-05T00:00:00Z", in_use: false, due_for_removal: true },
    { id: "p3", display_name: "Former person", created_at: "2025-06-05T00:00:00Z", in_use: true, due_for_removal: false },
  ],
};

const meta: Meta<typeof ImportedPeoplePanel> = {
  title: "Components/ImportedPeoplePanel",
  component: ImportedPeoplePanel,
  decorators: [withToast()],
  args: { orgId: "org-1" },
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(LIST);
    spyOn(api, "put").mockResolvedValue({});
    spyOn(api, "post").mockResolvedValue({});
    spyOn(api, "delete").mockResolvedValue({});
  },
};
export default meta;

type Story = StoryObj<typeof ImportedPeoplePanel>;

/** Each person with whether it is in use or due for removal; only an unused person offers Remove. */
export const List: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = within(await canvas.findByRole("table", { name: "Imported people" }));
    await expect(table.getByText("Due for removal")).toBeInTheDocument();
    await expect(table.getAllByText("In use")).toHaveLength(2);
    await expect(table.getAllByRole("button", { name: "Remove" })).toHaveLength(1);
    await expect(table.getAllByRole("button", { name: "Anonymise" })[2]).toBeDisabled();
    await expect(canvas.getByLabelText(/Offer unused imported people/)).toHaveValue(90);
  },
};

/** Anonymising asks first, then calls the endpoint. */
export const AnonymiseAsksFirst: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click((await canvas.findAllByRole("button", { name: "Anonymise" }))[0]);
    const dialog = within(within(canvasElement.ownerDocument.body).getByRole("dialog", { name: "Anonymise Alex Morgan?" }));
    await userEvent.click(dialog.getByRole("button", { name: "Anonymise" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/v1/orgs/org-1/imported-people/p1/anonymise"));
  },
};

/** Removing an unused person asks first, then deletes. */
export const RemoveAsksFirst: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Remove" }));
    const dialog = within(within(canvasElement.ownerDocument.body).getByRole("dialog", { name: "Remove Kim Ito?" }));
    await userEvent.click(dialog.getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith("/api/v1/orgs/org-1/imported-people/p2"));
  },
};

/** The retention age is saved through the organisation's advanced settings, and cleared to never list anyone. */
export const SavesTheRetentionAge: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const field = await canvas.findByLabelText(/Offer unused imported people/);
    await userEvent.clear(field);
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith("/api/v1/orgs/org-1/advanced-settings", { imported_person_retention_days: null }));
  },
};

export const Empty: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue({ retention_days: null, people: [] });
  },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("No imported people.")).toBeInTheDocument();
  },
};
