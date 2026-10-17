import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { LINKS_PROJECT_ID } from "../testing/artefactLinksFixtures";
import { buildSupersessionApi, buildUniverseApi, FOCUS_ID, SUPERSESSION_FOCUS_ID } from "../testing/linkTraceUniverse";
import { withRouter } from "../testing/storybook-helpers";
import { LinkTraceModal } from "./LinkTraceModal";

/**
 * The dialog behind the Links panel's "Trace" button: Tree and Map tabs over the same record.
 */
const meta: Meta<typeof LinkTraceModal> = {
  title: "Components/LinkTraceModal",
  component: LinkTraceModal,
  decorators: [withRouter("/")],
  // The trace views are part of the a11y acceptance: violations fail here, not just show in the UI.
  parameters: { a11y: { test: "error" } },
  args: {
    projectId: LINKS_PROJECT_ID, artefactType: "requirement", artefactId: FOCUS_ID, rootLabel: "REQ-002 Store reports",
    api: buildUniverseApi(), onClose: fn(),
  },
};
export default meta;

type Story = StoryObj<typeof LinkTraceModal>;

const dialog = () => within(document.body).getByRole("dialog", { name: "Trace: REQ-002 Store reports" });

export const SwitchesBetweenTreeAndMap: Story = {
  play: async () => {
    const body = within(document.body);
    await expect(await body.findByRole("tab", { name: "Tree", selected: true })).toBeInTheDocument();
    await expect(await within(dialog()).findByRole("region", { name: /Upstream/ })).toBeInTheDocument();
    await userEvent.click(body.getByRole("tab", { name: "Map" }));
    await expect(await within(dialog()).findByRole("region", { name: /Map of the records linked to/ })).toBeInTheDocument();
    await userEvent.click(body.getByRole("tab", { name: "Tree" }));
    await expect(await within(dialog()).findByRole("region", { name: /Downstream/ })).toBeInTheDocument();
  },
};

export const ClosesWhenARecordLinkIsFollowed: Story = {
  play: async ({ args }) => {
    const link = await within(dialog()).findByRole("link", { name: "REQ-001 Keep reports" });
    link.addEventListener("click", (e) => e.preventDefault());
    await userEvent.click(link);
    await expect(args.onClose).toHaveBeenCalled();
  },
};

export const HideInactiveRecordsAppliesToBothViews: Story = {
  args: { api: buildSupersessionApi(), artefactType: "decision", artefactId: SUPERSESSION_FOCUS_ID, rootLabel: "DEC-002 Adopt dual-redundant controllers" },
  play: async () => {
    const body = within(document.body);
    const dialogEl = within(await body.findByRole("dialog", { name: /^Trace:/ }));
    await dialogEl.findByRole("link", { name: "DEC-001 Single controller with hot-swap" });
    await userEvent.click(dialogEl.getByRole("checkbox", { name: "Hide inactive records" }));
    await waitFor(() => expect(dialogEl.queryByRole("link", { name: /DEC-001/ })).not.toBeInTheDocument());
    await expect(await dialogEl.findByRole("link", { name: "AV-PERF-001 Acquire GPS lock" })).toBeInTheDocument();
    // The choice follows the user to the other view.
    await userEvent.click(body.getByRole("tab", { name: "Map" }));
    await dialogEl.findByRole("link", { name: /AV-PERF-001/ });
    await expect(dialogEl.queryByRole("link", { name: /DEC-001/ })).not.toBeInTheDocument();
  },
};
