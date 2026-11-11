import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { AnnouncementNotice } from "../api/types";
import { AnnouncementBanner } from "./AnnouncementBanner";

const NOTICES: AnnouncementNotice[] = [
  { id: "n1", title: "Release tonight", body: "Expect a short pause.", severity: "warning", scope: "server", dismissible: true },
  { id: "n2", title: "Team day", body: "", severity: "information", scope: "organisation", dismissible: true },
];

/** The banner above a signed-in page: platform messages plus the current organisation's. */
const meta: Meta<typeof AnnouncementBanner> = {
  title: "Components/AnnouncementBanner",
  component: AnnouncementBanner,
  args: { organizationId: "org-1" },
  beforeEach: () => {
    window.localStorage.removeItem("announcements.dismissed");
  },
};
export default meta;

type Story = StoryObj<typeof AnnouncementBanner>;

/** The organisation id is sent so its own messages join the platform's. */
export const ShowsTheActiveNoticesForTheOrganisation: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(NOTICES);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("Release tonight")).toBeInTheDocument();
    await expect(canvas.getByText("Team day")).toBeInTheDocument();
    await expect(api.get).toHaveBeenCalledWith("/api/v1/announcements/active?organization_id=org-1");
  },
};

/** Without an organisation only the platform's messages are requested. */
export const WithoutAnOrganisationOnlyThePlatformIsAsked: Story = {
  args: { organizationId: null },
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([NOTICES[0]]);
  },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("Release tonight")).toBeInTheDocument();
    await expect(api.get).toHaveBeenCalledWith("/api/v1/announcements/active");
  },
};

/** A dismissed notice stays hidden in this browser. */
export const DismissIsRememberedInThisBrowser: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(NOTICES);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Dismiss Team day" }));
    await waitFor(() => expect(canvas.queryByText("Team day")).not.toBeInTheDocument());
    await expect(canvas.getByText("Release tonight")).toBeInTheDocument();
    await expect(JSON.parse(window.localStorage.getItem("announcements.dismissed") ?? "[]")).toEqual(["n2"]);
  },
};

/** A notice that is not dismissible has no close control and shows even if it was dismissed before. */
export const ANoticeThatIsNotDismissibleCannotBeClosed: Story = {
  beforeEach: () => {
    window.localStorage.setItem("announcements.dismissed", JSON.stringify(["n3"]));
    spyOn(api, "get").mockResolvedValue([{ id: "n3", title: "Demo resets daily", body: "", severity: "critical", scope: "server", dismissible: false }]);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("Demo resets daily")).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: /Dismiss/ })).not.toBeInTheDocument();
  },
};

/** The banner is a pinned strip, and the chrome below it follows its measured height. */
export const PinsAboveTheTopBarAndPublishesItsHeight: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(NOTICES);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByText("Release tonight");
    const bar = canvasElement.querySelector<HTMLElement>(".announcement-bar")!;
    await expect(getComputedStyle(bar).position).toBe("sticky");
    await waitFor(() => expect(document.documentElement.style.getPropertyValue("--announcement-height")).toBe(`${bar.offsetHeight}px`));
    await expect(bar.offsetHeight).toBeGreaterThan(0);
    await userEvent.click(canvas.getByRole("button", { name: "Dismiss Release tonight" }));
    await userEvent.click(canvas.getByRole("button", { name: "Dismiss Team day" }));
    await waitFor(() => expect(document.documentElement.style.getPropertyValue("--announcement-height")).toBe("0px"));
  },
};

/** A failed load shows nothing rather than an error over the page. */
export const AFailedLoadShowsNothing: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockRejectedValue(new Error("offline"));
  },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    await expect(canvasElement.querySelector("section")).toBeNull();
  },
};
