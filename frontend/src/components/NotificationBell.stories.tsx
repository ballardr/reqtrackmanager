import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, within } from "storybook/test";

import { api } from "../api/client";
import { buildNotification, withRouter } from "../testing/storybook-helpers";
import { NotificationBell } from "./NotificationBell";

const meta: Meta<typeof NotificationBell> = {
  title: "Components/NotificationBell",
  component: NotificationBell,
  decorators: [withRouter("/")],
};
export default meta;

type Story = StoryObj<typeof NotificationBell>;

export const UnreadNotifications: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([
      buildNotification({ id: "n1", title: "New comment", read_at: null }),
      buildNotification({ id: "n2", title: "Change request approved", read_at: "2026-02-01T09:00:00Z" }),
    ]);
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const bell = canvas.getByRole("button", { name: "Notifications" });
    await expect(canvas.getByText("1")).toBeInTheDocument();
    await userEvent.click(bell);
    await expect(canvas.getByText("New comment")).toBeInTheDocument();
    await expect(canvas.getByText("Change request approved")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Mark all read" })).toBeInTheDocument();
  },
};

export const Empty: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([]);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Notifications" }));
    await expect(canvas.getByText("No notifications yet.")).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Mark all read" })).not.toBeInTheDocument();
  },
};

export const NinetyNinePlusUnread: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(
      Array.from({ length: 120 }, (_, i) => buildNotification({ id: `n${i}`, read_at: null }))
    );
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("99+")).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...UnreadNotifications, globals: { theme: "light" } };
export const DarkTheme: Story = { ...UnreadNotifications, globals: { theme: "dark" } };
