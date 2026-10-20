import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { buildProposedLink } from "../testing/storybook-helpers";
import { ProposedLinksSection } from "./ProposedLinksSection";

/**
 * The "Proposed links" card of a change request's page: what the request proposes and what became of
 * each link.
 */
const meta: Meta<typeof ProposedLinksSection> = {
  title: "Components/ProposedLinksSection",
  component: ProposedLinksSection,
};
export default meta;

type Story = StoryObj<typeof ProposedLinksSection>;

export const PendingLinks: Story = {
  args: { links: [buildProposedLink(), buildProposedLink({ phrase: "Is a dependency of", direction: "incoming", other_label: "AUTH-003 — Lockout" })] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Proposed links")).toBeInTheDocument();
    await expect(canvas.getAllByText("Pending")).toHaveLength(2);
    await expect(canvas.getByText("Is a dependency of")).toBeInTheDocument();
  },
};

export const OutcomesAfterTheDecision: Story = {
  args: {
    links: [
      buildProposedLink({ outcome: "merged" }),
      buildProposedLink({ outcome: "declined", other_label: "Audit log retention", other_type_label: "Decision" }),
      buildProposedLink({ outcome: "skipped", other_label: null, outcome_reason: "The linked record was not found." }),
    ],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Merged")).toBeInTheDocument();
    await expect(canvas.getByText("Left out")).toBeInTheDocument();
    await expect(canvas.getByText("Not valid")).toBeInTheDocument();
    await expect(canvas.getByText("The linked record was not found.")).toBeInTheDocument();
  },
};

/** A link into a parent or child project shows which one. */
export const LinkIntoAnotherProject: Story = {
  args: { links: [buildProposedLink({ other_project_id: "project-parent", other_project_name: "Programme" })] },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("In Programme")).toBeInTheDocument();
  },
};
