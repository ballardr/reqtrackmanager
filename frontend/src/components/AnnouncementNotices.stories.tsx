import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import type { AnnouncementNotice } from "../api/types";
import { AnnouncementNotices } from "./AnnouncementNotices";

const NOTICES: AnnouncementNotice[] = [
  { id: "n1", title: "Outage under way", body: "Saving is unavailable.\nWe are working on it.", severity: "critical", scope: "server", dismissible: true },
  { id: "n2", title: "Team day", body: "", severity: "information", scope: "organisation", dismissible: true },
];

/** The announcements a reader sees, on the login pages and as the signed-in banner. */
const meta: Meta<typeof AnnouncementNotices> = {
  title: "Components/AnnouncementNotices",
  component: AnnouncementNotices,
  args: { notices: NOTICES },
};
export default meta;

type Story = StoryObj<typeof AnnouncementNotices>;

/** A critical notice is announced as an alert; the message keeps its line breaks. */
export const SeverityDecidesTheAnnouncementRole: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const alert = canvas.getByRole("alert");
    await expect(within(alert).getByText("Critical:")).toBeInTheDocument();
    await expect(within(alert).getByText(/Saving is unavailable\./)).toHaveStyle({ whiteSpace: "pre-wrap" });
    await expect(canvas.getByRole("status")).toHaveTextContent("Team day");
  },
};

/** Severity reads by an icon and its name, not by a badge, so colour is never the only cue. */
export const SeverityHasAnIconAndATextNameNotABadge: Story = {
  play: async ({ canvasElement }) => {
    const marks = canvasElement.querySelectorAll(".announcement-severity");
    await expect(marks).toHaveLength(2);
    for (const mark of marks) await expect(mark.querySelector("svg")).not.toBeNull();
    await expect(marks[0]).toHaveTextContent("Critical:");
    await expect(marks[1]).toHaveTextContent("Information:");
    await expect(canvasElement.querySelector(".badge")).toBeNull();
  },
};

/** A notice that is not dismissible has no close control even when a handler is given. */
export const NotDismissibleHasNoCloseControl: Story = {
  args: {
    onDismiss: fn(),
    notices: [{ id: "n4", title: "Demo accounts", body: "Resets daily.", severity: "warning", scope: "server", dismissible: false }],
  },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("button")).not.toBeInTheDocument();
    await expect(within(canvasElement).getByText("Demo accounts")).toBeInTheDocument();
  },
};

/** Text is always plain: markup and links in a message are shown as typed, never rendered. */
export const MessageTextIsNeverRenderedAsMarkup: Story = {
  args: {
    notices: [{ id: "n3", title: "<b>Bold</b> title", body: '<a href="https://evil.example">Sign in</a>', severity: "warning", scope: "organisation", dismissible: true }],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("<b>Bold</b> title")).toBeInTheDocument();
    await expect(canvas.getByText('<a href="https://evil.example">Sign in</a>')).toBeInTheDocument();
    await expect(canvas.queryByRole("link")).not.toBeInTheDocument();
  },
};

/** The login pages offer no Dismiss; the banner does, and says which scope each notice has. */
export const DismissAndScopeAppearOnlyWhenAsked: Story = {
  args: { onDismiss: fn(), showScope: true },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Platform")).toBeInTheDocument();
    await expect(canvas.getByText("Organisation")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Dismiss Team day" }));
    await expect(args.onDismiss).toHaveBeenCalledWith("n2");
  },
};

/** In the banner each notice is a full-width strip, not a card. */
export const BarVariantDrawsFullWidthStrips: Story = {
  args: { bar: true },
  play: async ({ canvasElement }) => {
    const strips = canvasElement.querySelectorAll(".announcement--bar");
    await expect(strips).toHaveLength(2);
    await expect(getComputedStyle(strips[0]).borderRadius).toBe("0px");
  },
};

export const NoDismissWithoutAHandler: Story = {
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("button")).not.toBeInTheDocument();
  },
};

export const NothingWhenThereAreNoNotices: Story = {
  args: { notices: [] },
  play: async ({ canvasElement }) => {
    await expect(canvasElement.querySelector("section")).toBeNull();
  },
};
