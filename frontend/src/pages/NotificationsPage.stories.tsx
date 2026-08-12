import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, within } from "storybook/test";

import { api } from "../api/client";
import { buildNotification, withRouter } from "../testing/storybook-helpers";
import { NotificationsPage } from "./NotificationsPage";

const meta: Meta<typeof NotificationsPage> = {
  title: "Pages/NotificationsPage",
  component: NotificationsPage,
  decorators: [withRouter("/notifications")],
};
export default meta;

type Story = StoryObj<typeof NotificationsPage>;

export const UnreadAndRead: Story = {
  beforeEach: () => {
    spyOn(api, "getPage").mockResolvedValue({
      items: [
        buildNotification({ id: "n1", title: "New comment", read_at: null }),
        buildNotification({ id: "n2", title: "Change request approved", read_at: "2026-02-01T09:00:00Z" }),
      ],
      total: 2,
    });
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("New comment")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Mark all read" })).toBeInTheDocument();
  },
};

export const MarkAllRead: Story = {
  beforeEach: () => {
    spyOn(api, "getPage").mockResolvedValue({ items: [buildNotification({ id: "n1", read_at: null })], total: 1 });
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Mark all read" }));
    await expect(api.post).toHaveBeenCalledWith("/api/v1/notifications/read-all");
  },
};

export const LoadMore: Story = {
  beforeEach: () => {
    spyOn(api, "getPage").mockResolvedValue({
      items: Array.from({ length: 30 }, (_, i) => buildNotification({ id: `n${i}` })),
      total: 45,
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: /30\/45/ })).toBeInTheDocument();
  },
};

export const Empty: Story = {
  beforeEach: () => {
    spyOn(api, "getPage").mockResolvedValue({ items: [], total: 0 });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("No notifications yet.")).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...UnreadAndRead, globals: { theme: "light" } };
export const DarkTheme: Story = { ...UnreadAndRead, globals: { theme: "dark" } };
