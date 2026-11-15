import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { buildUser, withAuth, withRouter, withToast } from "../../testing/storybook-helpers";
import { buildRecordDiagram, mockArchitectureReads, PROJECT_ID } from "./architectureFixtures";
import { RecordDiagramsCard } from "./RecordDiagramsCard";

const meta: Meta<typeof RecordDiagramsCard> = {
  title: "Modules/Architecture/RecordDiagramsCard",
  component: RecordDiagramsCard,
  args: { projectId: PROJECT_ID, record: { kind: "element", id: "el-1" } },
  decorators: [withAuth(buildUser({ id: "user-1" })), withRouter(`/projects/${PROJECT_ID}/modules/architecture/elements/el-1`), withToast()],
};
export default meta;

type Story = StoryObj<typeof RecordDiagramsCard>;

/** One of each type: each links to its own editor, and the row says the type and how the element appears. */
export const ListsABlockDiagramAndAStateMachineDiagram: Story = {
  beforeEach: () => {
    mockArchitectureReads({
      recordDiagrams: [
        buildRecordDiagram(),
        buildRecordDiagram({ id: "dgm-2", unique_code: "DGM-002", name: "Vehicle", usage: "inside", via_element_id: "el-0", via_element_code: "ELM-000", via_element_name: "Platform" }),
        { ...buildRecordDiagram({ id: "smd-1", unique_code: "SMD-001", name: "Gateway modes", usage: "describes", status: "active" }), kind: "state_machine" },
      ],
    });
  },
  play: async ({ canvasElement }) => {
    const card = within(await within(canvasElement).findByRole("region", { name: "Diagrams" }));
    await expect(card.getByRole("link", { name: /DGM-001 Main system/ })).toHaveAttribute("href", `/projects/${PROJECT_ID}/modules/architecture/diagrams/dgm-1`);
    await expect(card.getByRole("link", { name: /SMD-001 Gateway modes/ })).toHaveAttribute("href", `/projects/${PROJECT_ID}/modules/architecture/state-machine-diagrams/smd-1`);
    await expect(card.getByText(/Block diagram · Placed/)).toBeInTheDocument();
    await expect(card.getByText(/Block diagram · Inside ELM-000 Platform/)).toBeInTheDocument();
    await expect(card.getByText(/State machine diagram · Describes this element/)).toBeInTheDocument();
    await expect(card.getByText("Active")).toBeInTheDocument();
  },
};

/** A connection's card says whether a diagram draws its own line or one rolled up to ancestors of its ends. */
export const ALineIsDrawnOrRolledUp: Story = {
  args: { record: { kind: "connection", id: "con-1" } },
  beforeEach: () => {
    mockArchitectureReads({
      recordDiagrams: [buildRecordDiagram({ usage: "drawn" }), buildRecordDiagram({ id: "dgm-2", unique_code: "DGM-002", name: "Overview", usage: "rolled_up" })],
    });
  },
  play: async ({ canvasElement }) => {
    const card = within(await within(canvasElement).findByRole("region", { name: "Diagrams" }));
    await expect(card.getByText(/Block diagram · Drawn/)).toBeInTheDocument();
    await expect(card.getByText(/Block diagram · Rolled up/)).toBeInTheDocument();
  },
};

/** A record on no diagram says so, so the card is still there to find. */
export const SaysWhenThereAreNoDiagrams: Story = {
  beforeEach: () => { mockArchitectureReads({ recordDiagrams: [] }); },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("Not on any diagram.")).toBeInTheDocument();
  },
};

/** Many diagrams are one list, in the order the server gave. */
export const ManyDiagramsAreOneList: Story = {
  beforeEach: () => {
    mockArchitectureReads({
      recordDiagrams: Array.from({ length: 12 }, (_v, i) => buildRecordDiagram({ id: `dgm-${i}`, unique_code: `DGM-${String(i + 1).padStart(3, "0")}`, name: `View ${i + 1}` })),
    });
  },
  play: async ({ canvasElement }) => {
    const card = within(await within(canvasElement).findByRole("region", { name: "Diagrams" }));
    await expect(card.getAllByRole("link")).toHaveLength(12);
  },
};

/** The action is drawn on the heading's line. */
export const ShowsItsActionOnTheHeadingLine: Story = {
  args: { action: <button className="btn">New thing</button> },
  beforeEach: () => { mockArchitectureReads({ recordDiagrams: [buildRecordDiagram()] }); },
  play: async ({ canvasElement }) => {
    const card = within(await within(canvasElement).findByRole("region", { name: "Diagrams" }));
    await expect(card.getByRole("button", { name: "New thing" })).toBeInTheDocument();
  },
};
