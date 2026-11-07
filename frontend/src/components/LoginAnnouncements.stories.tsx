import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import { LoginAnnouncements } from "./LoginAnnouncements";

/** The messages above a login form, read without signing in. */
const meta: Meta<typeof LoginAnnouncements> = {
  title: "Components/LoginAnnouncements",
  component: LoginAnnouncements,
};
export default meta;

type Story = StoryObj<typeof LoginAnnouncements>;

/** The plain login page asks for the platform's messages only. */
export const PlainLoginPageShowsThePlatformMessages: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([{ id: "n1", title: "Demo instance", body: "Use the demo account.", severity: "information", scope: "server" }]);
  },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("Demo instance")).toBeInTheDocument();
    await expect(api.get).toHaveBeenCalledWith("/api/v1/announcements/login");
  },
};

/** An organisation's branded page sends its slug so the organisation's messages join the platform's. */
export const BrandedPageSendsTheSlug: Story = {
  args: { organizationSlug: "acme corp" },
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([]);
  },
  play: async () => {
    await waitFor(() => expect(api.get).toHaveBeenCalledWith("/api/v1/announcements/login?organization_slug=acme%20corp"));
  },
};

/** The form must stay usable: a failed read shows nothing at all. */
export const AFailedReadShowsNothing: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockRejectedValue(new Error("rate limited"));
  },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    await expect(canvasElement.querySelector("section")).toBeNull();
  },
};
