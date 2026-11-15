import type { Decorator, Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { buildUser, withStatefulAuth, withThemeProvider, withToast } from "../../testing/storybook-helpers";
import {
  buildDiagramModel, buildElement, buildModelElement, mockArchitectureReads, PROJECT_ID,
} from "./architectureFixtures";
import { DiagramEditorPage } from "./DiagramEditorPage";

/**
 * A block diagram whose Gateway has one state machine diagram and whose Orders has two: the badge on the box, the Selection card
 * action and the Outline column that open them (with the way back carried in the address), and the link that selects a box.
 */
const ELEMENTS = [
  buildElement(),
  buildElement({ id: "el-2", unique_code: "ELM-002", name: "Orders", ports: [] }),
  buildElement({ id: "el-3", unique_code: "ELM-003", name: "Firewall", ports: [] }),
  buildElement({ id: "el-4", unique_code: "ELM-004", name: "Cache", ports: [] }),
];
const MODEL = buildDiagramModel({
  elements: [
    buildModelElement({ state_machines: [{ id: "smd-1", unique_code: "SMD-001", name: "Gateway modes" }] }),
    buildModelElement({
      id: "el-2", unique_code: "ELM-002", name: "Orders",
      state_machines: [{ id: "smd-2", unique_code: "SMD-002", name: "Order life" }, { id: "smd-3", unique_code: "SMD-003", name: "Order faults" }],
    }),
    buildModelElement({ id: "el-3", unique_code: "ELM-003", name: "Firewall" }),
    buildModelElement({ id: "el-4", unique_code: "ELM-004", name: "Cache" }),
  ],
});

/** Shows where the router went when a click leaves the editor. */
function Where() {
  const location = useLocation();
  return <p data-testid="where">{location.pathname}{location.search}</p>;
}

/** The editor at the address a story names in `parameters.start` (a story-level router would nest inside this one); any other address renders where it is, so a story can assert the navigation. */
const editorAt: Decorator = (Story, context) => {
  const start = typeof context.parameters.start === "string" ? context.parameters.start : EDITOR;
  return (
    <MemoryRouter initialEntries={[start]}>
      <Routes>
        <Route path="/projects/:projectId/modules/architecture/diagrams/:diagramId" element={<Story />} />
        <Route path="*" element={<Where />} />
      </Routes>
    </MemoryRouter>
  );
};

const EDITOR = `/projects/${PROJECT_ID}/modules/architecture/diagrams/dgm-1`;
const MACHINES = `/projects/${PROJECT_ID}/modules/architecture/state-machine-diagrams`;

const meta: Meta<typeof DiagramEditorPage> = {
  title: "Modules/Architecture/DiagramEditorPage/State machine links",
  component: DiagramEditorPage,
  decorators: [withStatefulAuth(buildUser({ id: "user-1", ui_preferences: {} })), editorAt, withToast(), withThemeProvider()],
  loaders: [async () => { await import("../../components/GraphCanvasView"); return {}; }],
  beforeEach: () => { mockArchitectureReads({ elements: ELEMENTS, diagramModel: MODEL }); },
};
export default meta;

type Story = StoryObj<typeof DiagramEditorPage>;

/** Focuses a node and selects it with Enter. */
async function select(canvas: ReturnType<typeof within>, name: string) {
  const node = await canvas.findByLabelText(`${name}, node`);
  node.focus();
  await userEvent.keyboard("{Enter}");
}

export const OnlyABoxWithAStateMachineDiagramHasABadge: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByLabelText("Gateway, node");
    expect(await canvas.findByRole("button", { name: "Open state machine diagram" })).toBeInTheDocument();
    expect(canvas.getByRole("button", { name: "Open a state machine diagram (2 available)" })).toHaveTextContent("2");
    expect(canvas.getAllByRole("button", { name: /^Open (a )?state machine diagram/ })).toHaveLength(2);
  },
};

export const TheBadgeOpensTheStateMachineDiagramAndNamesTheDiagramItCameFrom: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Open state machine diagram" }));
    await waitFor(() => expect(canvas.getByTestId("where")).toHaveTextContent(`${MACHINES}/smd-1?from=dgm-1`));
  },
};

export const ABadgeWithSeveralDiagramsOffersAListOfThem: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Open a state machine diagram (2 available)" }));
    const list = await within(document.body).findByRole("list", { name: "Open a state machine diagram (2 available)" });
    expect(within(list).getAllByRole("button").map((b) => b.textContent)).toEqual(["SMD-002 Order life", "SMD-003 Order faults"]);
    await userEvent.click(within(list).getByRole("button", { name: /Order faults/ }));
    await waitFor(() => expect(canvas.getByTestId("where")).toHaveTextContent(`${MACHINES}/smd-3?from=dgm-1`));
  },
};

export const TheSelectionCardOffersTheSameRouteForTheKeyboard: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Gateway");
    const actions = await canvas.findByRole("group", { name: "Actions" });
    await userEvent.click(within(actions).getByRole("button", { name: "Open state machine diagram" }));
    await waitFor(() => expect(canvas.getByTestId("where")).toHaveTextContent(`${MACHINES}/smd-1?from=dgm-1`));
  },
};

export const SeveralDiagramsAreEntriesOfTheCardsMenu: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Orders");
    const actions = await canvas.findByRole("group", { name: "Actions" });
    expect(within(actions).queryByRole("button", { name: "Open state machine diagram" })).toBeNull();
    await userEvent.click(within(actions).getByRole("button", { name: "More actions" }));
    await userEvent.click(await within(document.body).findByRole("menuitem", { name: /SMD-003 Order faults/ }));
    await waitFor(() => expect(canvas.getByTestId("where")).toHaveTextContent(`${MACHINES}/smd-3?from=dgm-1`));
  },
};

export const AnElementWithNoStateMachineDiagramOffersNoSuchAction: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Firewall");
    const actions = await canvas.findByRole("group", { name: "Actions" });
    expect(within(actions).queryByRole("button", { name: /state machine diagram/i })).toBeNull();
  },
};

export const TheOutlineListsEachElementsStateMachineDiagrams: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("tab", { name: "Outline" }));
    // The tree shows the buttons beside each element.
    await userEvent.click(await canvas.findByRole("button", { name: "SMD-002 Order life" }));
    await waitFor(() => expect(canvas.getByTestId("where")).toHaveTextContent(`${MACHINES}/smd-2?from=dgm-1`));
  },
};

export const TheOutlineTableHasAStateMachineDiagramsColumn: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("tab", { name: "Outline" }));
    await userEvent.click(await canvas.findByRole("button", { name: "List view" }));
    const table = await canvas.findByRole("table", { name: "Elements" });
    await expect(within(table).getByRole("columnheader", { name: "State machine diagrams" })).toBeInTheDocument();
    const orders = within(table).getByRole("row", { name: /Orders/ });
    expect(within(orders).getAllByRole("button").map((b) => b.textContent)).toContain("SMD-003 Order faults");
    const firewall = within(table).getByRole("row", { name: /Firewall/ });
    expect(within(firewall).getByText("—", { selector: "td:last-child" })).toBeInTheDocument();
  },
};

export const UnsavedChangesAreConfirmedBeforeLeavingForAStateMachineDiagram: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Firewall");
    await userEvent.keyboard("{ArrowRight}");
    await waitFor(() => expect(canvas.getByRole("button", { name: "Save" })).toBeEnabled());
    await userEvent.click(canvas.getByRole("button", { name: "Open state machine diagram" }));
    const dialog = await within(document.body).findByRole("dialog");
    expect(within(dialog).getByText("Leave this diagram?")).toBeInTheDocument();
    expect(canvas.queryByTestId("where")).toBeNull();
    await userEvent.click(within(dialog).getByRole("button", { name: "Leave" }));
    await waitFor(() => expect(canvas.getByTestId("where")).toHaveTextContent(`${MACHINES}/smd-1?from=dgm-1`));
  },
};

/** Whether the box named `name` is drawn selected. */
function isSelectedBox(canvas: ReturnType<typeof within>, name: string): boolean {
  return canvas.getByLabelText(`${name}, node`).closest(".react-flow__node")?.classList.contains("selected") ?? false;
}

export const ALinkThatNamesABoxSelectsItAndTheSelectionCardShowsIt: Story = {
  parameters: { start: `${EDITOR}?select=el-2` },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByLabelText("Orders, node");
    await waitFor(() => expect(isSelectedBox(canvas, "Orders")).toBe(true));
    const actions = await canvas.findByRole("group", { name: "Actions" });
    expect(within(actions).getByRole("button", { name: "Remove from diagram" })).toBeInTheDocument();
  },
};

export const SelectingSomethingElseEndsTheLinksSelection: Story = {
  parameters: { start: `${EDITOR}?select=el-2` },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByLabelText("Orders, node");
    await waitFor(() => expect(isSelectedBox(canvas, "Orders")).toBe(true));
    await select(canvas, "Firewall");
    await waitFor(() => expect(isSelectedBox(canvas, "Firewall")).toBe(true));
    expect(isSelectedBox(canvas, "Orders")).toBe(false);
    // Clearing the selection does not bring the linked box back.
    await userEvent.click(canvasElement.querySelector(".react-flow__pane")!);
    await waitFor(() => expect(isSelectedBox(canvas, "Firewall")).toBe(false));
    expect(isSelectedBox(canvas, "Orders")).toBe(false);
  },
};

export const ALinkNamingAnElementTheDiagramDoesNotDrawSelectsNothing: Story = {
  parameters: { start: `${EDITOR}?select=el-99` },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByLabelText("Gateway, node");
    expect(isSelectedBox(canvas, "Gateway")).toBe(false);
    expect(isSelectedBox(canvas, "Orders")).toBe(false);
    expect(canvas.queryByRole("button", { name: "Remove from diagram" })).toBeNull();
  },
};
