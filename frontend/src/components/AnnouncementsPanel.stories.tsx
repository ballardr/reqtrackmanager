import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../api/client";
import { buildAnnouncement, withToast } from "../testing/storybook-helpers";
import { AnnouncementsPanel } from "./AnnouncementsPanel";

const ACTIVE = buildAnnouncement();
const SENT = buildAnnouncement({
  id: "announcement-2", title: "Release notes", body: "", severity: "information", show_on_login: false,
  notified_at: "2026-11-02T10:00:00Z", notified_count: 12,
});
const ENDED = buildAnnouncement({ id: "announcement-3", title: "Old notice", severity: "critical", status: "ended", ends_at: "2026-10-01T00:00:00Z" });

/** Announcement administration for one scope, shared by Server Management and Organisation Admin. */
const meta: Meta<typeof AnnouncementsPanel> = {
  title: "Components/AnnouncementsPanel",
  component: AnnouncementsPanel,
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof AnnouncementsPanel>;

/** Each message shows its severity, status, login-page flag and whether it was already sent. */
export const ListsMessagesWithStatusAndSend: Story = {
  args: { scope: { kind: "server" } },
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue({ items: [ACTIVE, SENT, ENDED] });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("Planned maintenance")).toBeInTheDocument();
    await expect(canvas.getByText("Warning")).toBeInTheDocument();
    await expect(canvas.getByText("Critical")).toBeInTheDocument();
    await expect(canvas.getAllByText("Login pages")).toHaveLength(2);
    await expect(canvas.getByText("Ended")).toBeInTheDocument();
    await expect(canvas.getByText(/Sent to 12 people on/)).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Send Old notice as a notification" })).toBeDisabled();
    await expect(canvas.queryByRole("button", { name: "Send Release notes as a notification" })).not.toBeInTheDocument();
    await expect(api.get).toHaveBeenCalledWith("/api/v1/system/announcements");
  },
};

export const EmptyScopeSaysSo: Story = {
  args: { scope: { kind: "organisation", organizationId: "org-1" } },
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue({ items: [] });
  },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("No messages.")).toBeInTheDocument();
    await expect(api.get).toHaveBeenCalledWith("/api/v1/orgs/org-1/announcements");
  },
};

/** A new message is posted with its window as UTC instants and the login flag. */
export const NewMessageSavesThroughTheApi: Story = {
  args: { scope: { kind: "organisation", organizationId: "org-1" } },
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue({ items: [] });
    spyOn(api, "post").mockResolvedValue({});
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "New message" }));
    const dialog = within(await within(document.body).findByRole("dialog", { name: "New message" }));
    await userEvent.type(dialog.getByRole("textbox", { name: /Title/ }), "Office closed");
    await userEvent.type(dialog.getByRole("textbox", { name: "Message" }), "Closed on Friday.");
    await userEvent.type(dialog.getByLabelText("Show from"), "2030-05-01T09:00");
    await userEvent.type(dialog.getByLabelText("Show until"), "2030-05-02T09:00");
    await userEvent.click(dialog.getByRole("checkbox", { name: /Show on the login pages/ }));
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/v1/orgs/org-1/announcements", {
      title: "Office closed", body: "Closed on Friday.", severity: "information",
      starts_at: new Date(2030, 4, 1, 9, 0).toISOString(), ends_at: new Date(2030, 4, 2, 9, 0).toISOString(), show_on_login: true,
    }));
  },
};

/** An end before the start blocks Save, and the server's own refusal is shown in the dialog. */
export const InvalidWindowBlocksSaveAndServerErrorsShow: Story = {
  args: { scope: { kind: "organisation", organizationId: "org-1" } },
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue({ items: [] });
    spyOn(api, "post").mockRejectedValue(new ApiError(422, "An organisation message cannot contain a web address."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "New message" }));
    const dialog = within(await within(document.body).findByRole("dialog", { name: "New message" }));
    await userEvent.type(dialog.getByRole("textbox", { name: /Title/ }), "Notice");
    await userEvent.type(dialog.getByLabelText("Show from"), "2030-05-02T09:00");
    await userEvent.type(dialog.getByLabelText("Show until"), "2030-05-01T09:00");
    await expect(dialog.getByText("The end must be after the start.")).toBeInTheDocument();
    await expect(dialog.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.clear(dialog.getByLabelText("Show until"));
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await expect(await dialog.findByText("An organisation message cannot contain a web address.")).toBeInTheDocument();
  },
};

/** Editing replaces the fields of that message. */
export const EditPutsTheMessage: Story = {
  args: { scope: { kind: "server" } },
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue({ items: [ACTIVE] });
    spyOn(api, "put").mockResolvedValue({});
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Edit message Planned maintenance" }));
    const dialog = within(await within(document.body).findByRole("dialog", { name: "Edit message" }));
    await userEvent.type(dialog.getByRole("textbox", { name: /Title/ }), " tonight");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      "/api/v1/system/announcements/announcement-1",
      expect.objectContaining({ title: "Planned maintenance tonight", severity: "warning", show_on_login: true }),
    ));
  },
};

/** Sending asks first, names who it reaches, and posts once. */
export const SendAsksFirstAndNamesTheAudience: Story = {
  args: { scope: { kind: "server" } },
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue({ items: [ACTIVE] });
    spyOn(api, "post").mockResolvedValue({});
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Send Planned maintenance as a notification" }));
    const dialog = within(await within(document.body).findByRole("dialog"));
    await expect(dialog.getByText(/every active user on the platform/)).toBeInTheDocument();
    await userEvent.click(dialog.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/v1/system/announcements/announcement-1/notify", {}));
  },
};

/** An organisation's send names its members, and delete asks first. */
export const OrganisationSendNamesMembersAndDeleteConfirms: Story = {
  args: { scope: { kind: "organisation", organizationId: "org-1" } },
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue({ items: [ACTIVE] });
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Send Planned maintenance as a notification" }));
    const sendDialog = within(await within(document.body).findByRole("dialog"));
    await expect(sendDialog.getByText(/every active member of the organisation/)).toBeInTheDocument();
    await userEvent.click(within(await within(document.body).findByRole("dialog")).getByRole("button", { name: "Cancel" }));
    await userEvent.click(canvas.getByRole("button", { name: "Delete message Planned maintenance" }));
    await userEvent.click(await within(document.body).findByRole("button", { name: "Delete" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith("/api/v1/orgs/org-1/announcements/announcement-1"));
  },
};
