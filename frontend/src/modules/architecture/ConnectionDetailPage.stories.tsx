import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { currentLifecycleStep } from "../../testing/lifecycleTrack";
import { recordActionNames } from "../../testing/recordActions";
import { buildUser, withAuth, withRouter, withToast } from "../../testing/storybook-helpers";
import { buildConnection, buildRecordDiagram, mockArchitectureReads, PROJECT_ID } from "./architectureFixtures";
import { ConnectionDetailPage } from "./ConnectionDetailPage";

const meta: Meta<typeof ConnectionDetailPage> = {
  title: "Modules/Architecture/ConnectionDetailPage",
  component: ConnectionDetailPage,
  decorators: [
    withAuth(buildUser({ id: "user-1" })),
    withRouter(`/projects/${PROJECT_ID}/modules/architecture/connections/con-1`, "/projects/:projectId/modules/architecture/connections/:connectionId"),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof ConnectionDetailPage>;

export const ShowsBothEndsWithPortsAndLinksToThem: Story = {
  beforeEach: () => { mockArchitectureReads({ connection: buildConnection() }); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("heading", { name: /Client traffic/ })).toBeInTheDocument();
    const source = canvas.getByRole("link", { name: /ELM-001 Gateway \(HTTPS API\)/ });
    await expect(source).toHaveAttribute("href", `/projects/${PROJECT_ID}/modules/architecture/elements/el-1`);
    await expect(canvas.getByRole("link", { name: /ELM-002 Orders/ })).toBeInTheDocument();
    await expect(canvas.getByText("One-way, source to target")).toBeInTheDocument();
  },
};

/** A draft connection promotes to Proposed; Activate directly and Reject are rows of the actions menu. */
export const TheLifecycleTrackPromotesAndTheMenuOffersTheOtherMoves: Story = {
  beforeEach: () => { mockArchitectureReads({ connection: buildConnection({ status: "draft" }) }); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("button", { name: "Next step: Proposed" })).toBeInTheDocument();
    await expect(currentLifecycleStep(canvasElement)).toBe("Draft");
    await expect((await recordActionNames(canvas, "Connection")).slice(0, 3)).toEqual(["Promote to Proposed", "Activate directly", "Reject"]);
  },
};

/** The Diagrams card is directly under the details, before the Realisation card, and says how each diagram draws the line. */
export const DiagramsCardFollowsTheDetailsCard: Story = {
  beforeEach: () => {
    mockArchitectureReads({
      connection: buildConnection({ realises: [{ id: "con-9", unique_code: "CON-009", name: "Outer" } as never] }),
      recordDiagrams: [buildRecordDiagram({ usage: "rolled_up" })],
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByText(/Block diagram · Rolled up/);
    const cards = Array.from(canvasElement.querySelectorAll("section.card")).map((c) => c.getAttribute("aria-label"));
    await expect(cards.slice(0, 2)).toEqual(["Details", "Diagrams"]);
  },
};

/** An end the viewer cannot read shows only its code, with no link. */
export const LockedEndShowsOnlyItsCode: Story = {
  beforeEach: () => {
    mockArchitectureReads({ connection: buildConnection({ target_locked: true, target_element_name: "" }) });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("heading", { name: /Client traffic/ });
    await expect(canvas.getByText("(not visible)")).toBeInTheDocument();
    await expect(canvas.queryByRole("link", { name: /ELM-002/ })).not.toBeInTheDocument();
  },
};

/** The connections it realises and the ones that realise it are listed as links, and appear only when there are any. */
export const ListsWhatItRealisesAndWhatRealisesIt: Story = {
  beforeEach: () => {
    mockArchitectureReads({
      connection: buildConnection({
        realises: [{ id: "con-9", unique_code: "CON-009", name: "Platform uplink", status: "active" }],
        realised_by: [{ id: "con-10", unique_code: "CON-010", name: "Gateway uplink", status: "draft" }],
      }),
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("heading", { name: /Client traffic/ });
    await expect(canvas.getByRole("link", { name: "CON-009" })).toHaveAttribute(
      "href", `/projects/${PROJECT_ID}/modules/architecture/connections/con-9`,
    );
    await expect(canvas.getByRole("link", { name: "CON-010" })).toBeInTheDocument();
  },
};

export const ShowsNoRealisationCardWhenThereAreNone: Story = {
  beforeEach: () => { mockArchitectureReads({ connection: buildConnection() }); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("heading", { name: /Client traffic/ });
    await expect(canvas.queryByText("Realisation")).not.toBeInTheDocument();
  },
};
