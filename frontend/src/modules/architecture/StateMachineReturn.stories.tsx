import type { Decorator, Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { buildUser, withAuth, withThemeProvider, withToast } from "../../testing/storybook-helpers";
import { buildElement, buildRecordDiagram, mockArchitectureReads, PROJECT_ID } from "./architectureFixtures";
import { StateMachineEditorPage } from "./StateMachineEditorPage";

/**
 * The way back from a state machine diagram to the block diagram it was opened from: a Return link when the address names a
 * readable block diagram (`?from=`), otherwise an Open in diagram menu of the block diagrams that draw the element, and
 * nothing when there are none.
 */
const MACHINE = `/projects/${PROJECT_ID}/modules/architecture/state-machine-diagrams/smd-1`;
const BLOCKS = [
  buildRecordDiagram(),
  buildRecordDiagram({ id: "dgm-2", unique_code: "DGM-002", name: "Deployment view", usage: "inside" }),
  buildRecordDiagram({ id: "smd-1", kind: "state_machine", unique_code: "SMD-001", name: "Gateway modes", usage: "describes" }),
];

/** Shows where the router went when a click leaves the editor. */
function Where() {
  const location = useLocation();
  return <p data-testid="where">{location.pathname}{location.search}</p>;
}

/** The editor at the address a story names in `parameters.start` (a story-level router would nest inside this one). */
const editorAt: Decorator = (Story, context) => {
  const start = typeof context.parameters.start === "string" ? context.parameters.start : `${MACHINE}?from=dgm-1`;
  return (
    <MemoryRouter initialEntries={[start]}>
      <Routes>
        <Route path="/projects/:projectId/modules/architecture/state-machine-diagrams/:diagramId" element={<Story />} />
        <Route path="*" element={<Where />} />
      </Routes>
    </MemoryRouter>
  );
};

const meta: Meta<typeof StateMachineEditorPage> = {
  title: "Modules/Architecture/StateMachineEditorPage/Return to the block diagram",
  component: StateMachineEditorPage,
  decorators: [withAuth(buildUser({ id: "user-1" })), editorAt, withToast(), withThemeProvider()],
  loaders: [async () => { await import("../../components/GraphCanvasView"); return {}; }],
  beforeEach: () => { mockArchitectureReads({ elements: [buildElement()], recordDiagrams: BLOCKS }); },
};
export default meta;

type Story = StoryObj<typeof StateMachineEditorPage>;

export const AReadableFromGivesAReturnLinkThatSelectsTheElement: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const link = await canvas.findByRole("link", { name: /^Return to DGM-001/ });
    expect(link).toHaveAttribute("href", `/projects/${PROJECT_ID}/modules/architecture/diagrams/dgm-1?select=el-1`);
    expect(canvas.queryByRole("button", { name: "Open in diagram" })).toBeNull();
    // The list's back link is still there beside it.
    expect(canvas.getByRole("link", { name: /Diagrams$/ })).toBeInTheDocument();
  },
};

export const WithoutAFromAnOpenInDiagramMenuListsTheBlockDiagramsThatDrawTheElement: Story = {
  parameters: { start: MACHINE },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Open in diagram" }));
    const menu = await within(document.body).findByRole("menu");
    // Only block diagrams: the state machine diagram itself is not a place to go.
    expect(within(menu).getAllByRole("menuitem").map((i) => i.textContent?.trim())).toEqual(["DGM-001 Main system", "DGM-002 Deployment view"]);
    await userEvent.click(within(menu).getByRole("menuitem", { name: /DGM-002/ }));
    await waitFor(() => expect(canvas.getByTestId("where")).toHaveTextContent(
      `/projects/${PROJECT_ID}/modules/architecture/diagrams/dgm-2?select=el-1`,
    ));
  },
};

export const AFromThatCannotBeReadIsIgnored: Story = {
  parameters: { start: `${MACHINE}?from=dgm-9` },
  beforeEach: () => { mockArchitectureReads({ elements: [buildElement()], recordDiagrams: BLOCKS, unreadableDiagrams: ["dgm-9"] }); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    expect(await canvas.findByRole("button", { name: "Open in diagram" })).toBeInTheDocument();
    expect(canvas.queryByRole("link", { name: /^Return to/ })).toBeNull();
  },
};

export const AnElementDrawnOnNoBlockDiagramShowsNoWayBack: Story = {
  parameters: { start: MACHINE },
  beforeEach: () => { mockArchitectureReads({ elements: [buildElement()], recordDiagrams: [BLOCKS[2]] }); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("heading", { name: /Gateway modes/ });
    await waitFor(() => expect(canvas.queryByRole("button", { name: "Open in diagram" })).toBeNull());
    expect(canvas.queryByRole("link", { name: /^Return to/ })).toBeNull();
  },
};
