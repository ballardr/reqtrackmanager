import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api, ApiError } from "../../api/client";
import { buildPlace, openPlacementPicker } from "../../testing/placementsFixtures";
import { buttonHeightViolations } from "../../testing/buttonHeights";
import { expectLabelInName } from "../../testing/labelInName";
import { requiredCaptions } from "../../testing/requiredMarkers";
import { buildComment, buildPin } from "../../testing/recordCommentsFake";
import { buildUser, withAuth, withRouter, withThemeProvider, withToast } from "../../testing/storybook-helpers";
import {
  buildBoundaryScene, buildConnection, buildDiagram, buildDiagramModel, buildDiagramView, buildElement, buildLeader, buildModelElement, buildNote,
  buildViewNode, captureDownloads, FIREWALL_TOGGLE, mockArchitectureReads, PROJECT_ID, SYMBOL_SVG,
} from "./architectureFixtures";
import { DiagramEditorPage } from "./DiagramEditorPage";
import { chooseMenuRow } from "../../testing/menuTree";

const BASE = `/api/v1/projects/${PROJECT_ID}/modules/architecture`;
const ELEMENTS = [
  buildElement(),
  buildElement({ id: "el-2", unique_code: "ELM-002", name: "Orders", ports: [] }),
  buildElement({ id: "el-3", unique_code: "ELM-003", name: "Firewall", ports: [] }),
  buildElement({ id: "el-4", unique_code: "ELM-004", name: "Cache", ports: [] }),
];

const meta: Meta<typeof DiagramEditorPage> = {
  title: "Modules/Architecture/DiagramEditorPage",
  component: DiagramEditorPage,
  decorators: [
    withAuth(buildUser({ id: "user-1" })),
    withRouter(`/projects/${PROJECT_ID}/modules/architecture/diagrams/dgm-1`, "/projects/:projectId/modules/architecture/diagrams/:diagramId"),
    withToast(),
    withThemeProvider(),
  ],
  // The canvas is a lazily loaded chunk; fetching it first keeps a cold load from racing the stories' first wait.
  loaders: [async () => { await import("../../components/GraphCanvasView"); return {}; }],
  beforeEach: () => { mockArchitectureReads({ elements: ELEMENTS }); },
};
export default meta;

type Story = StoryObj<typeof DiagramEditorPage>;

/** Focuses a node, selects it with Enter and returns it. */
async function select(canvas: ReturnType<typeof within>, name: string) {
  const node = await canvas.findByLabelText(`${name}, node`);
  node.focus();
  await userEvent.keyboard("{Enter}");
  return node;
}

/** Chooses an editor tab (the Drawing tab is the default). */
async function openTab(canvas: ReturnType<typeof within>, name: "Drawing" | "Outline" | "Comments" | "Configuration") {
  await userEvent.click(await canvas.findByRole("tab", { name }));
}

/** Opens the diagram settings (the gear beside Export) and returns the switch for connection detail. */
async function openSettings(canvas: ReturnType<typeof within>) {
  await userEvent.click(await canvas.findByRole("button", { name: /^Diagram settings/ }));
  return within(document.body).findByRole("switch", { name: "Connection detail" });
}

/** Opens the "Add to diagram" menu and chooses an entry (the menu is a popover outside the story's canvas). */
async function addFromMenu(canvas: ReturnType<typeof within>, item: string) {
  await userEvent.click(await canvas.findByRole("button", { name: "Add to diagram" }));
  await userEvent.click(await within(document.body).findByRole("menuitem", { name: item }));
}

/** The toolbar's buttons and menu triggers are one height, and so are the Selection card's, at a wide and a narrow editor. */
export const ToolbarAndSelectionButtonsShareAHeight: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByLabelText("Gateway, node");
    await expect(canvas.getByRole("toolbar")).toBeInTheDocument();
    await expect(buttonHeightViolations(canvasElement)).toEqual([]);
    await select(canvas, "Gateway");
    await expect(buttonHeightViolations(canvasElement)).toEqual([]);
    // A line has its own Selection card.
    (await canvas.findByLabelText("Connection from Gateway to Orders")).focus();
    await userEvent.keyboard("{Enter}");
    await expect(buttonHeightViolations(canvasElement)).toEqual([]);
  },
};

/** The same check at a narrow width, where the toolbar wraps and each line is compared on its own. */
export const ToolbarButtonsShareAHeightWhenNarrow: Story = {
  decorators: [(Story) => <div style={{ width: 480 }}><Story /></div>],
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByLabelText("Gateway, node");
    await expect(buttonHeightViolations(canvasElement)).toEqual([]);
  },
};

export const DrawsBoxesAndLinesFromTheModelData: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("heading", { name: /Platform overview/ })).toBeInTheDocument();
    await expect(await canvas.findByLabelText("Gateway, node")).toBeInTheDocument();
    await expect(canvas.getByLabelText("Orders, node")).toBeInTheDocument();
    await expect(await canvas.findByLabelText("Connection from Gateway to Orders")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Save diagram" })).toBeDisabled();
    await openTab(canvas, "Configuration");
    await expect(await canvas.findByRole("switch", { name: "Security devices" })).toBeChecked();
  },
};

/** The editor's save reads "Save" and is named "Save diagram"; the element and connection cards read "Save" and keep their own names. */
export const TheSaveButtonsReadSaveAndAreNamedForWhatTheyStore: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expectLabelInName(await canvas.findByRole("button", { name: "Save diagram" }), "Save", "Save diagram");
    await select(canvas, "Gateway");
    const panel = within(await canvas.findByRole("region", { name: "Selection" }));
    await expectLabelInName(await panel.findByRole("button", { name: "Save element" }), "Save", "Save element");
    await expect(canvas.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
  },
};

export const MovingABoxEnablesSaveAndSendsTheLayoutWithTheVersion: Story = {
  beforeEach: () => { spyOn(api, "put").mockResolvedValue(buildDiagram({ version: 4 }) as never); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Gateway");
    await userEvent.keyboard("{ArrowRight}{ArrowRight}");
    const save = canvas.getByRole("button", { name: "Save diagram" });
    await waitFor(() => expect(save).toBeEnabled());
    await userEvent.click(save);
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      `${BASE}/diagrams/dgm-1/layout`,
      expect.objectContaining({
        version: 3,
        placements: expect.arrayContaining([expect.objectContaining({ element_id: "el-1" }), expect.objectContaining({ element_id: "el-3" })]),
      }),
    ));
  },
};

export const UndoReturnsToTheSavedLayout: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Gateway");
    await userEvent.keyboard("{ArrowDown}");
    await waitFor(() => expect(canvas.getByRole("button", { name: "Save diagram" })).toBeEnabled());
    await userEvent.click(canvas.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Save diagram" })).toBeDisabled());
    await userEvent.click(canvas.getByRole("button", { name: "Redo" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Save diagram" })).toBeEnabled());
  },
};

export const ASaveStaysSavedWhenALaterReadSupersedesItsReadBack: Story = {
  beforeEach: () => {
    spyOn(api, "put").mockImplementation((async (path: string) => buildDiagram({ version: path.endsWith("/layout") ? 4 : 5 })) as never);
    const reads = (api.get as unknown as { getMockImplementation: () => typeof api.get }).getMockImplementation();
    let views = 0;
    // The read-back that follows the save (the second view read) never answers, as when a slow response is overtaken.
    spyOn(api, "get").mockImplementation((async (path: string, ...rest: unknown[]) => {
      if (path.split("?")[0].endsWith("/view") && ++views === 2) return new Promise(() => undefined);
      return (reads as unknown as (...args: unknown[]) => unknown)(path, ...rest);
    }) as never);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Gateway");
    await userEvent.keyboard("{ArrowRight}");
    await waitFor(() => expect(canvas.getByRole("button", { name: "Save diagram" })).toBeEnabled());
    await userEvent.click(canvas.getByRole("button", { name: "Save diagram" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1));
    await userEvent.click(await openSettings(canvas));
    await waitFor(() => expect(api.put).toHaveBeenCalledTimes(2));
    // What was saved is the baseline, so nothing is left to save and undoing the move is still possible.
    await waitFor(() => expect(canvas.getByRole("button", { name: "Save diagram" })).toBeDisabled());
  },
};

export const RemovingABoxLeavesTheElementInTheModel: Story = {
  beforeEach: () => {
    spyOn(api, "put").mockResolvedValue(buildDiagram({ version: 4 }) as never);
    spyOn(api, "delete").mockResolvedValue(undefined as never);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Orders");
    await userEvent.click(await canvas.findByRole("button", { name: "Remove from diagram" }));
    await waitFor(() => expect(canvas.queryByLabelText("Orders, node")).not.toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Save diagram" }));
    await waitFor(() => expect(api.put).toHaveBeenCalled());
    const body = (api.put as unknown as { mock: { calls: [string, { placements: { element_id: string }[] }][] } }).mock.calls[0][1];
    expect(body.placements.map((p) => p.element_id)).not.toContain("el-2");
    expect(api.delete).not.toHaveBeenCalled();
  },
};

/**
 * The Delete key takes the selected box off the drawing from anywhere on the page but a text field, Undo puts it back, and the
 * element stays in the model.
 */
export const TheDeleteKeyRemovesTheSelectedBoxFromAnywhereButATextField: Story = {
  beforeEach: () => { spyOn(api, "delete").mockResolvedValue(undefined as never); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Orders");
    const name = canvas.getByRole("textbox", { name: /^Name/ });
    await userEvent.click(name);
    await userEvent.keyboard("{Backspace}");
    await expect(canvas.getByLabelText("Orders, node")).toBeInTheDocument(); // the field kept the key
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(canvas.getByLabelText("Orders, node")).toHaveFocus());
    canvas.getByRole("button", { name: "Add to diagram" }).focus();
    await userEvent.keyboard("{Delete}");
    await waitFor(() => expect(canvas.queryByLabelText("Orders, node")).not.toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Undo" }));
    await expect(await canvas.findByLabelText("Orders, node")).toBeInTheDocument();
    expect(api.delete).not.toHaveBeenCalled();
  },
};

/** The key on a selected connection says where a connection is deleted, since a drawing holds no copy of it to remove. */
export const TheDeleteKeyOnAConnectionSaysWhereItIsDeleted: Story = {
  beforeEach: () => { spyOn(api, "delete").mockResolvedValue(undefined as never); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await selectLine(canvas);
    await userEvent.keyboard("{Delete}");
    await expect(await within(document.body).findByText(/Open the connection to delete it/)).toBeInTheDocument();
    await expect(canvas.getByLabelText("Orders, node")).toBeInTheDocument();
    expect(api.delete).not.toHaveBeenCalled();
  },
};

export const DeletingAnElementNeedsItsCodeTyped: Story = {
  beforeEach: () => { spyOn(api, "delete").mockResolvedValue(undefined as never); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Orders");
    await userEvent.click(await canvas.findByRole("button", { name: "Delete element…" }));
    const dialog = within(within(document.body).getByRole("dialog"));
    const confirm = dialog.getByRole("button", { name: "Delete" });
    await expect(confirm).toBeDisabled();
    await userEvent.type(dialog.getByRole("textbox"), "ELM-002");
    await userEvent.click(confirm);
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`${BASE}/elements/el-2`));
  },
};

export const AStaleVersionOffersAReloadInsteadOfOverwriting: Story = {
  beforeEach: () => { spyOn(api, "put").mockRejectedValue(new ApiError(409, "Version conflict")); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Gateway");
    await userEvent.keyboard("{ArrowRight}");
    await waitFor(() => expect(canvas.getByRole("button", { name: "Save diagram" })).toBeEnabled());
    await userEvent.click(canvas.getByRole("button", { name: "Save diagram" }));
    const alert = await canvas.findByRole("alert");
    await expect(alert).toHaveTextContent(/Someone else saved this diagram/);
    await expect(within(alert).getByRole("button", { name: "Reload diagram" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Save diagram" })).toBeDisabled();
  },
};

export const FlippingASwitchRedrawsAtOnceWithoutStoringOrReading: Story = {
  beforeEach: () => { spyOn(api, "put"); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByLabelText("Firewall, node");
    const reads = (api.get as unknown as { mock: { calls: unknown[] } }).mock.calls.length;
    await openTab(canvas, "Configuration");
    const toggle = await canvas.findByRole("switch", { name: "Security devices" });
    await userEvent.click(toggle);
    await openTab(canvas, "Drawing");
    await waitFor(() => expect(canvas.queryByLabelText("Firewall, node")).not.toBeInTheDocument());
    await openTab(canvas, "Configuration");
    await userEvent.click(await canvas.findByRole("switch", { name: "Security devices" }));
    await openTab(canvas, "Drawing");
    await expect(await canvas.findByLabelText("Firewall, node")).toBeInTheDocument();
    expect((api.get as unknown as { mock: { calls: unknown[] } }).mock.calls.length).toBe(reads);
    expect(api.put).not.toHaveBeenCalled();
  },
};

export const SwitchingOffAnElementBridgesTheLineAcrossIt: Story = {
  beforeEach: () => {
    mockArchitectureReads({
      elements: ELEMENTS,
      diagramModel: buildDiagramModel({
        connections: [
          buildConnection({ id: "con-in", unique_code: "CON-010", source_element_id: "el-1", target_element_id: "el-3", target_element_code: "ELM-003", target_element_name: "Firewall" }),
          buildConnection({ id: "con-out", unique_code: "CON-011", source_element_id: "el-3", source_element_code: "ELM-003", source_element_name: "Firewall", target_element_id: "el-2" }),
        ],
      }),
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByLabelText("Connection from Gateway to Firewall")).toBeInTheDocument();
    await openTab(canvas, "Configuration");
    await userEvent.click(await canvas.findByRole("switch", { name: "Security devices" }));
    await openTab(canvas, "Drawing");
    // The bridged line stands for both connections, so its label carries their count.
    const bridged = await canvas.findByLabelText("×2, connection from Gateway to Orders");
    await expect(bridged).toBeInTheDocument();
    bridged.focus();
    await userEvent.keyboard("{Enter}");
    const panel = within(await canvas.findByRole("region", { name: "Selection" }));
    await expect(panel.getByText(/bridged across hidden elements/)).toBeInTheDocument();
    await expect(panel.getByText(/Passes through: ELM-003 Firewall/)).toBeInTheDocument();
  },
};

export const AddingASwitchStoresTheWholeSet: Story = {
  beforeEach: () => { spyOn(api, "put").mockResolvedValue(buildDiagram({ version: 4 }) as never); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await openTab(canvas, "Configuration");
    await userEvent.click(await canvas.findByRole("button", { name: "Add switch" }));
    const dialog = within(within(document.body).getByRole("dialog"));
    await userEvent.type(await dialog.findByLabelText(/^Name/), "Hardware");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      `${BASE}/diagrams/dgm-1/toggles`,
      expect.objectContaining({
        version: 3,
        toggles: [
          expect.objectContaining({ id: "tg-1", name: "Security devices" }),
          expect.objectContaining({ id: null, name: "Hardware", default_on: true }),
        ],
      }),
    ));
  },
};

export const SelectingALineListsTheConnectionsBehindIt: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const edge = await canvas.findByLabelText("Connection from Gateway to Orders");
    edge.focus();
    await userEvent.keyboard("{Enter}");
    const panel = within(await canvas.findByRole("region", { name: "Selection" }));
    await expect(panel.getByRole("link", { name: "Open CON-001" })).toBeInTheDocument();
    await expect(panel.getByText(/1 connection/)).toBeInTheDocument();
  },
};

/** Selects the line between Gateway and Orders and returns the Selection card. */
async function selectLine(canvas: ReturnType<typeof within>, label: string | RegExp = "Connection from Gateway to Orders") {
  const edge = await canvas.findByLabelText(label);
  edge.focus();
  await userEvent.keyboard("{Enter}");
  return within(await canvas.findByRole("region", { name: "Selection" }));
}

export const ChoosingALineEndInTheSelectionCardIsStoredWithTheLayout: Story = {
  beforeEach: () => { spyOn(api, "put").mockResolvedValue(buildDiagram({ version: 4 }) as never); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const panel = await selectLine(canvas);
    // Gateway is at the left and Orders 300 to the right at the same height, so Automatic reads as the facing sides.
    await expect(panel.getByRole("combobox", { name: "Line starts at" })).toHaveDisplayValue("Automatic (Right)");
    await expect(panel.getByRole("combobox", { name: "Line ends at" })).toHaveDisplayValue("Automatic (Left)");
    await userEvent.selectOptions(panel.getByRole("combobox", { name: "Line starts at" }), "Bottom");
    await expect(panel.getByRole("combobox", { name: "Line starts at" })).toHaveDisplayValue("Bottom");
    await userEvent.click(canvas.getByRole("button", { name: "Save diagram" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      `${BASE}/diagrams/dgm-1/layout`,
      expect.objectContaining({
        anchors: [{ source_element_id: "el-1", target_element_id: "el-2", source_point: "bottom", target_point: null, points: [], smooth: false }],
      }),
    ));
  },
};

/** The Vertices section of the Selection card is the keyboard route to a line's route: add, position, curve, remove and reset. */
export const VerticesAreAddedPositionedAndRemovedInTheSelectionCard: Story = {
  beforeEach: () => { spyOn(api, "put").mockResolvedValue(buildDiagram({ version: 4 }) as never); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const panel = await selectLine(canvas);
    await expect(panel.getByText("No vertices. The line is straight.")).toBeInTheDocument();
    await expect(panel.getByRole("switch", { name: "Smooth curve" })).toBeDisabled();
    await userEvent.click(panel.getByRole("button", { name: "Add vertex" }));
    // Gateway and Orders are level, so the first vertex goes below the middle of the line.
    const x = await panel.findByRole("spinbutton", { name: "Vertex 1 X" });
    const y = panel.getByRole("spinbutton", { name: "Vertex 1 Y" });
    await expect(Number((y as HTMLInputElement).value)).toBeGreaterThan(0);
    await userEvent.clear(x);
    await userEvent.type(x, "210");
    await userEvent.tab();
    await expect(panel.getByRole("spinbutton", { name: "Vertex 1 X" })).toHaveValue(210);
    await expect(panel.getByRole("switch", { name: "Smooth curve" })).toBeEnabled();
    await userEvent.click(panel.getByRole("switch", { name: "Smooth curve" }));
    await userEvent.click(canvas.getByRole("button", { name: "Save diagram" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      `${BASE}/diagrams/dgm-1/layout`,
      expect.objectContaining({
        anchors: [expect.objectContaining({
          source_element_id: "el-1", target_element_id: "el-2", source_point: null, target_point: null,
          points: [expect.objectContaining({ x: 210 })], smooth: true,
        })],
      }),
    ));
  },
};

export const ResettingVerticesStraightensTheLineAndDropsTheAnchor: Story = {
  beforeEach: () => {
    mockArchitectureReads({
      elements: ELEMENTS,
      diagramView: buildDiagramView({
        anchors: [{ source_element_id: "el-1", target_element_id: "el-2", source_point: null, target_point: null, points: [{ x: 150, y: 120 }, { x: 250, y: 120 }], smooth: true }],
      }),
    });
    spyOn(api, "put").mockResolvedValue(buildDiagram({ version: 4 }) as never);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const panel = await selectLine(canvas);
    await expect(panel.getByRole("spinbutton", { name: "Vertex 2 Y" })).toHaveValue(120);
    await userEvent.click(panel.getByRole("button", { name: "Remove vertex 1" }));
    await expect(panel.queryByRole("spinbutton", { name: "Vertex 2 X" })).not.toBeInTheDocument();
    await userEvent.click(panel.getByRole("button", { name: "Reset vertices" }));
    await expect(panel.getByText("No vertices. The line is straight.")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Save diagram" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(`${BASE}/diagrams/dgm-1/layout`, expect.objectContaining({ anchors: [] })));
  },
};

/** A line whose anchor is stored for the opposite direction shows its vertices from the line's own source. */
export const VerticesOfAReversedAnchorAreListedFromTheLinesSource: Story = {
  beforeEach: () => {
    mockArchitectureReads({
      elements: ELEMENTS,
      diagramView: buildDiagramView({
        anchors: [{ source_element_id: "el-2", target_element_id: "el-1", source_point: null, target_point: "top", points: [{ x: 250, y: 90 }, { x: 150, y: 110 }], smooth: false }],
      }),
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const panel = await selectLine(canvas);
    // The line runs Gateway to Orders; the anchor was stored Orders to Gateway, so its points read in the other order.
    await expect(panel.getByRole("spinbutton", { name: "Vertex 1 X" })).toHaveValue(150);
    await expect(panel.getByRole("spinbutton", { name: "Vertex 2 X" })).toHaveValue(250);
    await expect(panel.getByRole("combobox", { name: "Line starts at" })).toHaveDisplayValue("Top");
  },
};

export const ChoosingAutomaticAgainRemovesTheAnchor: Story = {
  beforeEach: () => {
    mockArchitectureReads({
      elements: ELEMENTS,
      diagramView: buildDiagramView({ anchors: [{ source_element_id: "el-1", target_element_id: "el-2", source_point: "top", target_point: null, points: [], smooth: false }] }),
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const panel = await selectLine(canvas);
    await expect(panel.getByRole("combobox", { name: "Line starts at" })).toHaveDisplayValue("Top");
    await userEvent.selectOptions(panel.getByRole("combobox", { name: "Line starts at" }), "Automatic (Right)");
    await waitFor(() => expect(canvas.getByRole("button", { name: "Save diagram" })).toBeEnabled());
    await userEvent.click(canvas.getByRole("button", { name: "Undo" }));
    await expect(panel.getByRole("combobox", { name: "Line starts at" })).toHaveDisplayValue("Top");
    await waitFor(() => expect(canvas.getByRole("button", { name: "Save diagram" })).toBeDisabled());
  },
};

export const RemovingABoxDropsTheAnchorsOfItsLines: Story = {
  beforeEach: () => {
    mockArchitectureReads({
      elements: ELEMENTS,
      diagramView: buildDiagramView({ anchors: [{ source_element_id: "el-1", target_element_id: "el-2", source_point: "top", target_point: "bottom", points: [], smooth: false }] }),
    });
    spyOn(api, "put").mockResolvedValue(buildDiagram({ version: 4 }) as never);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Orders");
    await userEvent.click(await canvas.findByRole("button", { name: "Remove from diagram" }));
    await userEvent.click(canvas.getByRole("button", { name: "Save diagram" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(`${BASE}/diagrams/dgm-1/layout`, expect.objectContaining({ anchors: [] })));
  },
};

export const AnArchivedDiagramOffersNoLineEnds: Story = {
  beforeEach: () => {
    mockArchitectureReads({ elements: ELEMENTS, diagramView: buildDiagramView({ diagram: buildDiagram({ is_archived: true }) }) });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const panel = await selectLine(canvas);
    await expect(panel.queryByRole("combobox", { name: "Line starts at" })).not.toBeInTheDocument();
    await expect(panel.queryByRole("button", { name: "Add vertex" })).not.toBeInTheDocument();
  },
};

export const AddingAnElementDrawsItsConnectionsBeforeSaving: Story = {
  beforeEach: () => {
    mockArchitectureReads({
      elements: ELEMENTS,
      diagramModel: buildDiagramModel({
        connections: [
          buildConnection(),
          buildConnection({ id: "con-5", unique_code: "CON-005", target_element_id: "el-4", target_element_code: "ELM-004", target_element_name: "Cache" }),
        ],
      }),
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await addFromMenu(canvas, "Add existing elements");
    const dialog = within(within(document.body).getByRole("dialog"));
    await expect(dialog.queryByText("Gateway")).not.toBeInTheDocument();
    await userEvent.click(await dialog.findByRole("checkbox", { name: "Add Cache" }));
    await userEvent.click(dialog.getByRole("button", { name: "Add selected (1)" }));
    await expect(await canvas.findByLabelText("Cache, node")).toBeInTheDocument();
    await expect(await canvas.findByLabelText("Connection from Gateway to Cache")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Save diagram" })).toBeEnabled();
    await expect(canvas.getByRole("status")).toHaveTextContent("Unsaved changes.");
  },
};

/** A type chosen in the Add menu creates the element at once, named for its type, selected with the cursor in its name. */
export const AnElementIsCreatedAtOnceNamedForItsTypeAndSelected: Story = {
  beforeEach: () => {
    const created = buildElement({ id: "el-9", unique_code: "ELM-009", name: "Queue worker" });
    mockArchitectureReads({ elements: [...ELEMENTS, created] });
    spyOn(api, "post").mockResolvedValue(created as never);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await addFromMenu(canvas, "Service");
    await expect(await canvas.findByLabelText("Queue worker, node")).toBeInTheDocument();
    await expect(api.post).toHaveBeenCalledWith(
      `${BASE}/elements`, expect.objectContaining({ name: "Service 1", element_type_id: "et-1", parent_id: null, activate: false }),
    );
    await expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument();
    const panel = within(await canvas.findByRole("region", { name: "Selection" }));
    const name = await panel.findByRole("textbox", { name: "Name" });
    await waitFor(() => expect(name).toHaveFocus());
    await expect(name).toHaveValue("Queue worker");
    await expect(requiredCaptions(await canvas.findByRole("group", { name: "Element details" }))).toEqual(["Name", "Element type"]);
    await expect(canvas.getByRole("button", { name: "Save diagram" })).toBeEnabled();
  },
};

/** A refused create is an error message and nothing is added to the diagram. */
export const ARefusedElementCreateAddsNothingAndSaysWhy: Story = {
  beforeEach: () => { spyOn(api, "post").mockRejectedValue(new ApiError(403, "You may not create elements in this project.")); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await addFromMenu(canvas, "Service");
    await expect(await within(document.body).findByText("You may not create elements in this project.")).toBeInTheDocument();
    await expect(canvas.queryByLabelText("Service 1, node")).not.toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Save diagram" })).toBeDisabled();
  },
};

/** The default name is the first number not already in use. */
export const TheDefaultNameSkipsANumberAlreadyInUse: Story = {
  beforeEach: () => {
    mockArchitectureReads({ elements: [...ELEMENTS, buildElement({ id: "el-8", unique_code: "ELM-008", name: "Service 1", ports: [] })] });
    spyOn(api, "post").mockResolvedValue(buildElement({ id: "el-9", unique_code: "ELM-009", name: "Service 2" }) as never);
  },
  play: async ({ canvasElement }) => {
    await addFromMenu(within(canvasElement), "Service");
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`${BASE}/elements`, expect.objectContaining({ name: "Service 2" })));
  },
};
export const ANoteIsEditedInPlainText: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await addFromMenu(canvas, "Add note");
    const text = await canvas.findByRole("textbox", { name: "Note text" });
    await userEvent.type(text, "<b>Check with ops</b>");
    await userEvent.tab();
    const node = await canvas.findByLabelText("<b>Check with ops</b>, node");
    await expect(node).toBeInTheDocument();
    await expect(node.querySelector("b")).toBeNull();
  },
};

/** Clicks empty canvas at a position inside the pane (a real pointer click, so the canvas reports its position). */
async function clickPane(canvasElement: HTMLElement, at: { x: number; y: number }) {
  const pane = canvasElement.querySelector(".react-flow__pane") as HTMLElement;
  const rect = pane.getBoundingClientRect();
  await userEvent.pointer({ keys: "[MouseLeft]", target: pane, coords: { clientX: rect.left + at.x, clientY: rect.top + at.y } });
}

export const ANoteWithNoToneIsItsTextAloneWithNoCaption: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await addFromMenu(canvas, "Add note");
    const text = await canvas.findByRole("textbox", { name: "Note text" });
    await userEvent.type(text, "Plain label");
    await userEvent.tab();
    const boxed = await canvas.findByLabelText("Plain label, node");
    await expect(boxed.querySelector(".graph-node-caption")?.textContent).toBe("Note");
    await expect(boxed.querySelector(".graph-node")?.classList.contains("graph-node-dashed")).toBe(true);
    await userEvent.selectOptions(await noteField(canvas, "Tone"), "none");
    // Select another box, so the colours read are the note's own and not the selection ring's.
    await select(canvas, "Gateway");
    const plain = await canvas.findByLabelText("Plain label, node");
    const box = plain.querySelector(".graph-node") as HTMLElement;
    await expect(box.classList.contains("graph-node-tone-none")).toBe(true);
    await expect(box.classList.contains("graph-node-dashed")).toBe(false);
    await expect(plain.querySelector(".graph-node-caption")).toBeNull();
    await expect(getComputedStyle(box).backgroundColor).toBe("rgba(0, 0, 0, 0)");
    await expect(getComputedStyle(box).borderTopColor).toBe("rgba(0, 0, 0, 0)");
    // The wording is still the accessible name, and the tone's help lists None.
    await expect(within(plain).getByText("Plain label")).toBeInTheDocument();
  },
};

export const AnEmptyNoteWithNoToneKeepsAFaintOutlineSoItCanBeFound: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await addFromMenu(canvas, "Add note");
    await userEvent.selectOptions(await noteField(canvas, "Tone"), "none");
    await userEvent.tab();
    // Deselect by choosing another box, so the outline seen is the empty-note one and not the selection ring.
    await select(canvas, "Gateway");
    const empty = await canvas.findByLabelText("Empty note, node");
    const box = empty.querySelector(".graph-node") as HTMLElement;
    await expect(box.classList.contains("graph-node-placeholder")).toBe(true);
    await expect(getComputedStyle(box).borderTopStyle).toBe("dashed");
    await expect(getComputedStyle(box).borderTopColor).not.toBe("rgba(0, 0, 0, 0)");
  },
};

export const NoteModePlacesANoteAtEachClickAndEscapeLeavesIt: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByLabelText("Gateway, node");
    const noteToggle = canvas.getByRole("button", { name: "Note" });
    const commentToggle = canvas.getByRole("button", { name: "Comment" });
    await expect(noteToggle).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(noteToggle);
    await expect(noteToggle).toHaveAttribute("aria-pressed", "true");
    await clickPane(canvasElement, { x: 40, y: 260 });
    // The note is placed, selected, and its text has the cursor (add, then edit).
    const text = await canvas.findByRole("textbox", { name: "Note text" });
    await waitFor(() => expect(text).toHaveFocus());
    await expect(canvasElement.querySelectorAll('[aria-label$="Empty note, node"], [aria-label="Empty note, node"]').length).toBe(1);
    await userEvent.type(text, "First");
    await userEvent.tab();
    // The mode stays on, so a second click places a second note, and the first is not lost.
    await expect(noteToggle).toHaveAttribute("aria-pressed", "true");
    await clickPane(canvasElement, { x: 260, y: 260 });
    await waitFor(() => expect(canvasElement.querySelectorAll(".graph-node-tone").length).toBe(2));
    // Comment and Note are never both on.
    await userEvent.click(commentToggle);
    await expect(commentToggle).toHaveAttribute("aria-pressed", "true");
    await expect(noteToggle).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(noteToggle);
    await expect(noteToggle).toHaveAttribute("aria-pressed", "true");
    await expect(commentToggle).toHaveAttribute("aria-pressed", "false");
    // Escape leaves the mode, and a click then selects again instead of placing a note.
    (document.activeElement as HTMLElement | null)?.blur();
    await userEvent.keyboard("{Escape}");
    await expect(noteToggle).toHaveAttribute("aria-pressed", "false");
    await clickPane(canvasElement, { x: 500, y: 260 });
    await expect(canvasElement.querySelectorAll(".graph-node-tone").length).toBe(2);
  },
};

export const TheNoteSwitchExplainsBothStatesOnTheButton: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const noteToggle = await canvas.findByRole("button", { name: "Note" });
    await userEvent.hover(noteToggle);
    const tip = await within(document.body).findByRole("tooltip");
    await expect(tip).toHaveTextContent("On:");
    await expect(tip).toHaveTextContent("Off:");
    await expect(canvas.queryByRole("button", { name: /^Help: Note/ })).toBeNull();
  },
};

export const AnArchivedDiagramCannotPlaceNotes: Story = {
  beforeEach: () => {
    mockArchitectureReads({ elements: ELEMENTS, diagramView: buildDiagramView({ diagram: buildDiagram({ is_archived: true }) }) });
  },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByRole("button", { name: "Note" })).toBeDisabled();
  },
};

/** The note card's and the leader card's fields (the card is the second "Selection" region once a note or leader is chosen). */
const noteField = (canvas: ReturnType<typeof within>, name: string) => canvas.findByRole("combobox", { name });

/** Adds a note from the Add menu and a leader from its card, which becomes the selection (the leader card is then shown). */
async function addNoteWithLeader(canvas: ReturnType<typeof within>) {
  await addFromMenu(canvas, "Add note");
  await userEvent.click(await canvas.findByRole("button", { name: "Add leader" }));
  await canvas.findByText("Leader 1");
}

export const ANoteIsGivenAToneAndALeaderToABoxAndBothAreSaved: Story = {
  beforeEach: () => { spyOn(api, "put").mockResolvedValue(buildDiagram({ version: 4 }) as never); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await addFromMenu(canvas, "Add note");
    await userEvent.selectOptions(await noteField(canvas, "Tone"), "danger");
    await userEvent.click(await canvas.findByRole("button", { name: "Add leader" }));
    await userEvent.selectOptions(await noteField(canvas, "Points at"), "element:el-1");
    await waitFor(() => expect(canvasElement.querySelectorAll(".react-flow__edge.graph-leader").length).toBe(1));
    await expect(await noteField(canvas, "End style")).toHaveDisplayValue("Arrow");
    await userEvent.selectOptions(await noteField(canvas, "End style"), "dot");
    await userEvent.selectOptions(await noteField(canvas, "Starts at"), "right");
    await userEvent.click(canvas.getByRole("button", { name: "Save diagram" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      `${BASE}/diagrams/dgm-1/layout`,
      expect.objectContaining({
        notes: [expect.objectContaining({
          id: null, tone: "danger",
          leaders: [{
            id: null, kind: "element", element_id: "el-1", connection_id: null, state_id: null, transition_id: null, x: null, y: null,
            start_point: "right", points: [], smooth: false, start_style: "none", end_style: "dot",
          }],
        })],
      }),
    ));
  },
};

export const ANoteCanPointAtAConnectionByNameAndItsLeaderCanBeRemoved: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await addNoteWithLeader(canvas);
    const pointsAt = await noteField(canvas, "Points at");
    const option = within(pointsAt).getByRole("option", { name: /^Connection: CON-001/ });
    await userEvent.selectOptions(pointsAt, option);
    await waitFor(() => expect(canvasElement.querySelectorAll(".react-flow__edge.graph-leader").length).toBe(1));
    await userEvent.click(canvas.getByRole("button", { name: "Remove leader" }));
    await waitFor(() => expect(canvasElement.querySelectorAll(".react-flow__edge.graph-leader").length).toBe(0));
  },
};

export const ALeaderAddedFromTheCardEndsAtASpotSetByXAndYAndTheCardReturnsToTheNote: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await addNoteWithLeader(canvas);
    await waitFor(() => expect(canvasElement.querySelectorAll(".react-flow__edge.graph-leader").length).toBe(1));
    await expect(await noteField(canvas, "Points at")).toHaveDisplayValue("A spot on the canvas");
    const x = canvas.getByRole("spinbutton", { name: "Spot X" });
    await userEvent.clear(x);
    await userEvent.type(x, "640");
    await userEvent.tab();
    await waitFor(() => expect(canvas.getByRole("spinbutton", { name: "Spot X" })).toHaveValue(640));
    await userEvent.click(canvas.getByRole("button", { name: "Select note" }));
    await expect(await canvas.findByRole("list", { name: "Leaders" })).toBeInTheDocument();
    await expect(canvas.getByText(/Points at a spot/)).toBeInTheDocument();
  },
};

export const ALeaderToASwitchedOffBoxIsHiddenAndTheCardSaysSo: Story = {
  beforeEach: () => {
    mockArchitectureReads({
      elements: ELEMENTS,
      diagramView: buildDiagramView({
        toggles: [{ ...FIREWALL_TOGGLE, default_on: false, on: false }],
        notes: [buildNote({ leaders: [buildLeader({ kind: "element", element_id: "el-3", x: null, y: null })] })],
      }),
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Check with ops");
    await expect(await canvas.findByText(/points at something that is not drawn/)).toBeInTheDocument();
    expect(canvasElement.querySelectorAll(".react-flow__edge.graph-leader").length).toBe(0);
    await openTab(canvas, "Outline");
    await expect(await canvas.findByText(/Points at ELM-003 Firewall \(not drawn\)/)).toBeInTheDocument();
  },
};

export const AnArchivedDiagramShowsTheLeaderButOffersNoControls: Story = {
  beforeEach: () => {
    mockArchitectureReads({
      elements: ELEMENTS,
      diagramView: buildDiagramView({
        diagram: buildDiagram({ is_archived: true }), notes: [buildNote({ leaders: [buildLeader({ x: 400, y: -200 })] })],
      }),
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Check with ops");
    await waitFor(() => expect(canvasElement.querySelectorAll(".react-flow__edge.graph-leader").length).toBe(1));
    await expect(canvas.queryByRole("button", { name: "Add leader" })).toBeNull();
    await userEvent.click(await canvas.findByRole("button", { name: "Edit leader 1" }));
    await expect(await noteField(canvas, "Points at")).toBeDisabled();
  },
};

export const ASharedElementCannotBeDeletedFromHere: Story = {
  beforeEach: () => {
    mockArchitectureReads({
      elements: ELEMENTS,
      diagramView: buildDiagramView({ nodes: buildDiagramView().nodes.map((n) => (n.element_id === "el-2" ? { ...n, shared: true } : n)) }),
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Orders");
    await expect(await canvas.findByRole("button", { name: "Remove from diagram" })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Delete element…" })).not.toBeInTheDocument();
  },
};

/** A box's project components are set in the Selection card and stored at once, like its ports. */
export const AComponentIsAssignedToABoxFromTheSelectionCard: Story = {
  beforeEach: () => {
    mockArchitectureReads({ elements: ELEMENTS, placements: { "el-1": [buildPlace("c-hw", "k-cool")] } });
    spyOn(api, "put").mockResolvedValue({ placements: [buildPlace("c-hw", "k-cool"), buildPlace("c-sw")], can_edit: true, managed_on_record: false } as never);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Gateway");
    const panel = within(await canvas.findByRole("region", { name: "Selection" }));
    await expect((await panel.findAllByText("Hardware / Cooling")).length).toBeGreaterThan(0);
    await openPlacementPicker(panel);
    await userEvent.click(await within(document.body).findByRole("checkbox", { name: "Software" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/artefacts/architecture_element/el-1/placements`,
      { placements: [{ component_id: "c-hw", category_id: "k-cool" }, { component_id: "c-sw", category_id: null }] },
    ));
  },
};

/** A box shared from another owner has no Components control: a component belongs to one project's tree. */
export const ASharedBoxHasNoComponentsControl: Story = {
  beforeEach: () => {
    mockArchitectureReads({
      elements: ELEMENTS,
      placements: { "el-2": [buildPlace("c-sw")] },
      diagramView: buildDiagramView({ nodes: buildDiagramView().nodes.map((n) => (n.element_id === "el-2" ? { ...n, shared: true } : n)) }),
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Orders");
    const panel = within(await canvas.findByRole("region", { name: "Selection" }));
    await expect(await panel.findByRole("link", { name: "Open element" })).toBeInTheDocument();
    await expect(panel.queryByRole("group", { name: "Components" })).not.toBeInTheDocument();
  },
};

/** The Add menu's component filter narrows the elements offered to those placed in a ticked component. */
export const TheAddMenuListIsFilteredByComponent: Story = {
  beforeEach: () => {
    mockArchitectureReads({
      elements: [...ELEMENTS, buildElement({ id: "el-5", unique_code: "ELM-005", name: "Relay", ports: [] })],
      placements: { "el-4": [buildPlace("c-sw")], "el-5": [buildPlace("c-hw", "k-power")] },
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await addFromMenu(canvas, "Add existing elements");
    const dialog = within(within(document.body).getByRole("dialog"));
    await expect(await dialog.findByRole("checkbox", { name: "Add Cache" })).toBeInTheDocument();
    await expect(dialog.getByRole("checkbox", { name: "Add Relay" })).toBeInTheDocument();
    await userEvent.click(await dialog.findByRole("button", { name: "Component and category" }));
    await userEvent.click(await within(document.body).findByRole("checkbox", { name: "Software" }));
    await waitFor(() => expect(dialog.queryByRole("checkbox", { name: "Add Relay" })).not.toBeInTheDocument());
    await expect(dialog.getByRole("checkbox", { name: "Add Cache" })).toBeInTheDocument();
  },
};

export const AnArchivedDiagramCannotBeEdited: Story = {
  beforeEach: () => {
    mockArchitectureReads({ elements: ELEMENTS, diagramView: buildDiagramView({ diagram: buildDiagram({ is_archived: true }) }) });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByLabelText("Gateway, node");
    await expect(canvas.getByRole("button", { name: "Add to diagram" })).toBeDisabled();
    await expect(canvas.getByRole("button", { name: "Undo" })).toBeDisabled();
    await openTab(canvas, "Configuration");
    await expect(await canvas.findByRole("switch", { name: "Security devices" })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Add switch" })).not.toBeInTheDocument();
  },
};

export const ADetailedLineShowsItsTypeAndCount: Story = {
  beforeEach: () => {
    mockArchitectureReads({
      elements: ELEMENTS,
      diagramView: buildDiagramView({ diagram: buildDiagram({ connection_detail: true }) }),
      // Two parts inside Orders, each connected from Gateway, roll up to one line.
      diagramModel: buildDiagramModel({
        elements: [
          ...buildDiagramModel().elements,
          buildModelElement({ id: "el-5", unique_code: "ELM-005", name: "Orders API" }),
          buildModelElement({ id: "el-6", unique_code: "ELM-006", name: "Orders DB" }),
        ],
        parents: { "el-1": null, "el-2": null, "el-3": null, "el-4": null, "el-5": "el-2", "el-6": "el-2" },
        connections: [buildConnection({ id: "con-a", target_element_id: "el-5" }), buildConnection({ id: "con-b", target_element_id: "el-6" })],
      }),
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByLabelText("REST API ×2, connection from Gateway to Orders")).toBeInTheDocument();
    await expect(await openSettings(canvas)).toBeChecked();
  },
};

export const APlainDiagramMergesParallelLines: Story = {
  beforeEach: () => {
    mockArchitectureReads({
      elements: ELEMENTS,
      diagramModel: buildDiagramModel({ connections: [buildConnection(), buildConnection({ id: "con-2", unique_code: "CON-002" })] }),
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByLabelText("×2, connection from Gateway to Orders")).toBeInTheDocument();
  },
};

const PNG_SOURCE = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20" width="40" height="20"><rect width="40" height="20" fill="#0f766e"/></svg>';

/** Answers the export reads with a small SVG and Mermaid text; other blob reads (symbols) fall through to the fixture. */
function mockExportReads() {
  spyOn(api, "getForBlob").mockImplementation(async (path: string) => {
    if (path.includes("/svg")) return new Blob([PNG_SOURCE], { type: "image/svg+xml" });
    if (path.includes("/mermaid")) return new Blob(["flowchart LR\n"], { type: "text/plain" });
    return SYMBOL_SVG;
  });
}

/** Opens the Export menu and chooses an item. */
async function exportAs(canvas: ReturnType<typeof within>, item: string) {
  await userEvent.click(await canvas.findByRole("button", { name: "Export" }));
  await chooseMenuRow(item);
}

export const TheOutlineFollowsTheViewSwitches: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await openTab(canvas, "Outline");
    await expect(await within(await canvas.findByRole("region", { name: "Outline" })).findByRole("button", { name: /^ELM-003 Firewall/ })).toBeInTheDocument();
    await openTab(canvas, "Configuration");
    await userEvent.click(await canvas.findByRole("switch", { name: "Security devices" }));
    await openTab(canvas, "Outline");
    const outline = within(await canvas.findByRole("region", { name: "Outline" }));
    await waitFor(() => expect(outline.queryByRole("button", { name: /^ELM-003 Firewall/ })).not.toBeInTheDocument());
    await expect(outline.getByText(/1 hidden by view switches\./)).toBeInTheDocument();
  },
};

export const ChoosingInTheOutlineSelectsInTheSelectionCardAndOnTheCanvas: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await openTab(canvas, "Outline");
    const outline = within(await canvas.findByRole("region", { name: "Outline" }));
    await userEvent.click(await outline.findByRole("button", { name: /^ELM-002 Orders/ }));
    const panel = within(await canvas.findByRole("region", { name: "Selection" }));
    await expect(panel.getByText(/ELM-002 Orders/)).toBeInTheDocument();
    await expect(outline.getByRole("button", { name: /^ELM-002 Orders/ })).toHaveAttribute("aria-current", "true");
    await userEvent.click(outline.getByRole("button", { name: /^Line from/ }));
    await expect(await panel.findByRole("link", { name: "Open CON-001" })).toBeInTheDocument();
  },
};

export const ABoxAddedBeforeSavingIsInTheOutlineAtOnce: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await openTab(canvas, "Outline");
    const outline = within(await canvas.findByRole("region", { name: "Outline" }));
    await addFromMenu(canvas, "Add existing elements");
    const dialog = within(within(document.body).getByRole("dialog"));
    await userEvent.click(await dialog.findByRole("checkbox", { name: "Add Cache" }));
    await userEvent.click(dialog.getByRole("button", { name: "Add selected (1)" }));
    await expect(await outline.findByRole("button", { name: /^ELM-004 Cache/ })).toBeInTheDocument();
  },
};

/** The connection a "Connect to" choice creates: Gateway to Firewall, which no line joins yet. */
const NEW_CONNECTION = buildConnection({
  id: "con-8", unique_code: "CON-008", name: "", source_port_id: null, source_port_name: null, target_element_id: "el-3",
  target_element_code: "ELM-003", target_element_name: "Firewall", protocol: "",
});

/** Answers the post that creates `created`, and the diagram's model with it once it exists, so its line is drawn. */
function mockCreatedConnection(created: ReturnType<typeof buildConnection>) {
  let posted = false;
  spyOn(api, "post").mockImplementation(async () => { posted = true; return created as never; });
  const spy = api.get as unknown as { getMockImplementation: () => (...args: unknown[]) => Promise<unknown>; mockImplementation: (fn: unknown) => void };
  const original = spy.getMockImplementation();
  spy.mockImplementation(async (...args: unknown[]) => {
    const result = await original(...args);
    if (posted && String(args[0]).split("?")[0].endsWith("/diagrams/dgm-1/model")) {
      const model = result as { connections: unknown[] };
      return { ...model, connections: [...model.connections, created] };
    }
    return result;
  });
}

/** "Connect to" creates the connection at once with the suggested type, selects its line and puts the cursor in its name. */
export const ConnectToCreatesAConnectionAtOnceAndSelectsItsLine: Story = {
  beforeEach: () => { mockCreatedConnection(NEW_CONNECTION); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Gateway");
    const panel = within(await canvas.findByRole("region", { name: "Selection" }));
    const choose = await panel.findByRole("combobox", { name: /Connect to/ });
    // Only the other visible boxes are offered.
    await expect(within(choose).queryByRole("option", { name: /Gateway/ })).not.toBeInTheDocument();
    await userEvent.selectOptions(choose, "el-3");
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `${BASE}/connections`,
      expect.objectContaining({ source_element_id: "el-1", target_element_id: "el-3", connection_type_id: "ct-1", activate: false }),
    ));
    await expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument();
    const group = await canvas.findByRole("group", { name: "Connection details" });
    const details = within(group);
    await waitFor(() => expect(details.getByRole("textbox", { name: "Name" })).toHaveFocus());
    await expect(requiredCaptions(group)).toEqual(["Connection type", "Source element", "Target element"]);
  },
};

/** A project with no connection type cannot create a connection, so the dialog opens and links to where types are set up. */
export const AProjectWithNoConnectionTypeOpensTheDialogWithASetupLink: Story = {
  beforeEach: () => {
    const get = mockArchitectureReads({ elements: ELEMENTS });
    const original = get.getMockImplementation() as (...args: unknown[]) => Promise<unknown>;
    get.mockImplementation((async (...args: unknown[]) => (
      String(args[0]).split("?")[0].endsWith("/modules/architecture/connection-types") ? [] : original(...args)
    )) as never);
    spyOn(api, "post");
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Gateway");
    const panel = within(await canvas.findByRole("region", { name: "Selection" }));
    await userEvent.selectOptions(await panel.findByRole("combobox", { name: /Connect to/ }), "el-2");
    const dialog = within(await within(document.body).findByRole("dialog"));
    await expect(dialog.getByRole("heading", { name: "New connection" })).toBeInTheDocument();
    await expect(dialog.getByRole("link", { name: "Set up connection types" })).toHaveAttribute(
      "href", `/projects/${PROJECT_ID}/admin/architecture/architecture-connection-types`,
    );
    await expect(api.post).not.toHaveBeenCalled();
  },
};
export const TheDeleteKeyTakesTheSelectedBoxOffTheDiagramOnly: Story = {
  beforeEach: () => { spyOn(api, "delete").mockResolvedValue(undefined as never); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Orders");
    await userEvent.keyboard("{Delete}");
    await waitFor(() => expect(canvas.queryByLabelText("Orders, node")).not.toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "Save diagram" })).toBeEnabled();
    await userEvent.click(canvas.getByRole("button", { name: "Undo" }));
    await expect(await canvas.findByLabelText("Orders, node")).toBeInTheDocument();
    expect(api.delete).not.toHaveBeenCalled();
  },
};

export const AnArchivedDiagramIgnoresTheDeleteKey: Story = {
  beforeEach: () => {
    mockArchitectureReads({ elements: ELEMENTS, diagramView: buildDiagramView({ diagram: buildDiagram({ is_archived: true }) }) });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Orders");
    await userEvent.keyboard("{Delete}");
    await expect(canvas.getByLabelText("Orders, node")).toBeInTheDocument();
    await expect(canvas.queryByRole("combobox", { name: /Connect to/ })).not.toBeInTheDocument();
  },
};

export const ExportingSvgAsksTheServerForTheSwitchStatesOnThePage: Story = {
  beforeEach: () => { mockExportReads(); },
  play: async ({ canvasElement }) => {
    const names = captureDownloads();
    const canvas = within(canvasElement);
    await exportAs(canvas, "SVG image");
    await waitFor(() => expect(names).toEqual(["DGM-001-platform-overview.svg"]));
    expect(api.getForBlob).toHaveBeenCalledWith(`${BASE}/diagrams/dgm-1/svg?toggle_on=tg-1`);
  },
};

export const ExportingAfterSwitchingOffNamesTheSwitchAsOff: Story = {
  beforeEach: () => { mockExportReads(); },
  play: async ({ canvasElement }) => {
    const names = captureDownloads();
    const canvas = within(canvasElement);
    await openTab(canvas, "Configuration");
    await userEvent.click(await canvas.findByRole("switch", { name: "Security devices" }));
    await openTab(canvas, "Drawing");
    await exportAs(canvas, "Download Mermaid text");
    await waitFor(() => expect(names).toEqual(["DGM-001-platform-overview.mmd"]));
    expect(api.getForBlob).toHaveBeenCalledWith(`${BASE}/diagrams/dgm-1/mermaid?toggle_off=tg-1`);
  },
};

export const ExportingPngDrawsTheServersSvg: Story = {
  beforeEach: () => { mockExportReads(); },
  play: async ({ canvasElement }) => {
    const names = captureDownloads();
    await exportAs(within(canvasElement), "PNG image");
    await waitFor(() => expect(names).toEqual(["DGM-001-platform-overview.png"]));
  },
};

export const CopyingMermaidPutsTheTextOnTheClipboard: Story = {
  beforeEach: () => {
    mockExportReads();
    Object.defineProperty(navigator, "clipboard", { value: { writeText: fn().mockResolvedValue(undefined) }, configurable: true });
  },
  play: async ({ canvasElement }) => {
    await exportAs(within(canvasElement), "Copy Mermaid text");
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith("flowchart LR\n"));
  },
};

export const ExportingSavesAPendingLayoutFirst: Story = {
  beforeEach: () => {
    mockExportReads();
    spyOn(api, "put").mockResolvedValue(buildDiagram({ version: 4 }) as never);
  },
  play: async ({ canvasElement }) => {
    const names = captureDownloads();
    const canvas = within(canvasElement);
    await select(canvas, "Gateway");
    await userEvent.keyboard("{ArrowRight}");
    await waitFor(() => expect(canvas.getByRole("button", { name: "Save diagram" })).toBeEnabled());
    await exportAs(canvas, "SVG image");
    await waitFor(() => expect(names).toHaveLength(1));
    const put = (api.put as unknown as { mock: { invocationCallOrder: number[] } }).mock.invocationCallOrder[0];
    const read = (api.getForBlob as unknown as { mock: { calls: [string][]; invocationCallOrder: number[] } }).mock;
    const svgCall = read.calls.findIndex(([path]) => path.includes("/svg"));
    expect(put).toBeLessThan(read.invocationCallOrder[svgCall]);
  },
};

export const AFailedExportShowsAMessageAndDownloadsNothing: Story = {
  beforeEach: () => {
    spyOn(api, "getForBlob").mockImplementation(async (path: string) => {
      if (path.includes("/svg")) throw new ApiError(500, "Server error");
      return SYMBOL_SVG;
    });
  },
  play: async ({ canvasElement }) => {
    const names = captureDownloads();
    const canvas = within(canvasElement);
    await exportAs(canvas, "SVG image");
    await waitFor(() => expect(api.getForBlob).toHaveBeenCalledWith(expect.stringContaining("/svg")));
    // The menu is usable again once the failure has been handled.
    await waitFor(() => expect(canvas.getByRole("button", { name: "Export" })).toBeEnabled());
    expect(names).toEqual([]);
  },
};

export const TheAddMenuGroupsTheTypesByDomain: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Add to diagram" }));
    const menu = within(await within(document.body).findByRole("menu", { name: "Add to diagram" }));
    const labels = menu.getAllByRole("menuitem").map((item) => item.textContent?.trim());
    // A group of one item is a heading over it; "Other" holds two, so it is a row that is open at first.
    await expect(labels).toEqual(["Service", "Board", "Custom block", "Other", "Add existing elements", "Add note"]);
    for (const heading of ["New software element", "New hardware element", "New element", "Other"]) {
      await expect(menu.getByText(heading)).toBeInTheDocument();
    }
    // A type can be dragged onto the canvas as well as chosen.
    await expect(menu.getByRole("menuitem", { name: "Service" })).toHaveAttribute("draggable", "true");
    await expect(menu.getByRole("menuitem", { name: "Add note" })).toHaveAttribute("draggable", "false");
  },
};

export const ChoosingATypeInTheMenuOpensNoDialog: Story = {
  beforeEach: () => { spyOn(api, "post").mockResolvedValue(buildElement({ id: "el-9", unique_code: "ELM-009", name: "Board 1" }) as never); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await addFromMenu(canvas, "Board");
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`${BASE}/elements`, expect.objectContaining({ name: "Board 1" })));
    await expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument();
  },
};
export const TheConfigurationTabHoldsTheSettingsInsteadOfTheDrawing: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("tab", { name: "Drawing" })).toHaveAttribute("aria-selected", "true");
    await expect(canvas.queryByRole("region", { name: "View switches" })).not.toBeInTheDocument();
    await openTab(canvas, "Configuration");
    await expect(await canvas.findByRole("tab", { name: "Configuration" })).toHaveAttribute("aria-selected", "true");
    await expect(await canvas.findByRole("region", { name: "View switches" })).toBeInTheDocument();
    await expect(canvas.queryByRole("toolbar", { name: "Diagram editing" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("region", { name: "Outline" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("switch", { name: "Connection detail" })).not.toBeInTheDocument();
  },
};

export const TheOutlineHasItsOwnTabAndKeepsTheSelectionCard: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("region", { name: "Outline" })).not.toBeInTheDocument();
    await openTab(canvas, "Outline");
    await expect(await canvas.findByRole("tab", { name: "Outline" })).toHaveAttribute("aria-selected", "true");
    await expect(await canvas.findByRole("region", { name: "Outline" })).toBeInTheDocument();
    await expect(canvas.getByRole("region", { name: "Selection" })).toBeInTheDocument();
    await expect(canvas.getByRole("toolbar", { name: "Diagram editing" })).toBeInTheDocument();
    await expect(canvas.queryByLabelText("Gateway, node")).not.toBeInTheDocument();
  },
};

export const ConnectionDetailIsStoredFromTheGearBesideExport: Story = {
  beforeEach: () => { spyOn(api, "put").mockResolvedValue(buildDiagram({ version: 4, connection_detail: true }) as never); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("switch", { name: "Connection detail" })).not.toBeInTheDocument();
    await userEvent.click(await openSettings(canvas));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      `${BASE}/diagrams/dgm-1`, expect.objectContaining({ version: 3, connection_detail: true }),
    ));
  },
};

/** Line hops is a setting of the diagram: the gear's switch stores it with the version, as connection detail is stored. */
export const LineHopsIsStoredFromTheGear: Story = {
  beforeEach: () => { spyOn(api, "put").mockResolvedValue(buildDiagram({ version: 4, line_hops: true }) as never); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: /^Diagram settings/ }));
    const hops = await within(document.body).findByRole("switch", { name: "Line hops" });
    await expect(hops).not.toBeChecked();
    await userEvent.click(hops);
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      `${BASE}/diagrams/dgm-1`, expect.objectContaining({ version: 3, line_hops: true }),
    ));
  },
};

export const ADisplayNoteIsDrawnInsideItsBoxAndTheGearHidesItWithoutSaving: Story = {
  beforeEach: () => {
    mockArchitectureReads({
      elements: [buildElement({ display_note: "Public entry point." }), ...ELEMENTS.slice(1)],
      diagramView: buildDiagramView({
        nodes: [
          buildViewNode({ display_note: "Public entry point.", height: 160 }),
          buildViewNode({ placement_id: "pl-2", element_id: "el-2", unique_code: "ELM-002", name: "Orders", x: 300, y: 0 }),
        ],
        edges: [],
      }),
    });
    spyOn(api, "put");
    spyOn(api, "post");
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("Public entry point.")).toBeInTheDocument();
    await userEvent.click(await canvas.findByRole("button", { name: /^Diagram settings/ }));
    const notes = await within(document.body).findByRole("switch", { name: "Show notes" });
    await expect(notes).toBeChecked();
    await userEvent.click(notes);
    await waitFor(() => expect(canvas.queryByText("Public entry point.")).not.toBeInTheDocument());
    // A viewer's choice: nothing is stored and the layout is not made unsaved.
    await expect(api.put).not.toHaveBeenCalled();
    await expect(api.post).not.toHaveBeenCalled();
    await expect(canvas.getByRole("button", { name: "Save diagram" })).toBeDisabled();
    // The note is still read in full from the Selection card.
    await select(canvas, "Gateway");
    await expect(await canvas.findByText("Public entry point.")).toBeInTheDocument();
  },
};

export const UnsavedEditsAndTheSelectionSurviveAChangeOfTab: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Gateway");
    await userEvent.keyboard("{ArrowRight}");
    await waitFor(() => expect(canvas.getByRole("button", { name: "Save diagram" })).toBeEnabled());
    await openTab(canvas, "Configuration");
    await expect(await canvas.findByText(/unsaved changes; they are kept/)).toBeInTheDocument();
    await openTab(canvas, "Drawing");
    await expect(await canvas.findByLabelText("Gateway, node")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Save diagram" })).toBeEnabled();
    await expect(canvas.getByRole("status")).toHaveTextContent("Unsaved changes.");
    await expect(await canvas.findByRole("region", { name: "Selection" })).toHaveTextContent(/Gateway/);
  },
};

export const AnEditMadeWhileASaveIsReadBackIsKept: Story = {
  beforeEach: () => {
    spyOn(api, "put").mockResolvedValue(buildDiagram({ version: 4 }) as never);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Gateway");
    await userEvent.keyboard("{ArrowRight}");
    await waitFor(() => expect(canvas.getByRole("button", { name: "Save diagram" })).toBeEnabled());
    // Hold the reads that follow a save, so a second move can be made while the stored layout is being read back.
    const spy = api.get as unknown as { getMockImplementation: () => (...args: unknown[]) => Promise<unknown>; mockImplementation: (fn: unknown) => void };
    const original = spy.getMockImplementation();
    let release = () => {};
    const gate = new Promise<void>((resolve) => { release = resolve; });
    spy.mockImplementation(async (...args: unknown[]) => { await gate; return original(...args); });
    await userEvent.click(canvas.getByRole("button", { name: "Save diagram" }));
    await waitFor(() => expect(api.put).toHaveBeenCalled());
    await select(canvas, "Gateway");
    await userEvent.keyboard("{ArrowRight}");
    release();
    await waitFor(() => expect(canvas.getByRole("status")).toHaveTextContent("Unsaved changes."));
    await expect(canvas.getByRole("button", { name: "Save diagram" })).toBeEnabled();
    // Only the second move is unsaved: undoing it returns to what was stored.
    await userEvent.click(canvas.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Save diagram" })).toBeDisabled());
  },
};

export const EditingABoxInTheSelectionCardStoresTheElementAndKeepsPendingLayoutEdits: Story = {
  beforeEach: () => { spyOn(api, "put").mockResolvedValue(buildElement({ version: 2, name: "Edge gateway" }) as never); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Gateway");
    await userEvent.keyboard("{ArrowRight}");
    await waitFor(() => expect(canvas.getByRole("button", { name: "Save diagram" })).toBeEnabled());
    const panel = within(await canvas.findByRole("region", { name: "Selection" }));
    await expect(panel.queryByRole("button", { name: "Edit element" })).not.toBeInTheDocument();
    const name = await panel.findByRole("textbox", { name: "Name" });
    await userEvent.clear(name);
    await userEvent.type(name, "Edge gateway");
    await userEvent.click(panel.getByRole("button", { name: "Save element" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      `${BASE}/elements/el-1`, { name: "Edge gateway", version: 1 },
    ));
    await expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument();
    // The move made before the edit is still waiting to be saved.
    await expect(canvas.getByRole("button", { name: "Save diagram" })).toBeEnabled();
  },
};

/** The focus leaving the card's fields stores the change, as for a state; a blank name is refused with a message. */
export const LeavingTheElementFieldsStoresThemAndABlankNameIsRefused: Story = {
  beforeEach: () => { spyOn(api, "put").mockResolvedValue(buildElement({ version: 2, description: "Edge." }) as never); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Gateway");
    const panel = within(await canvas.findByRole("region", { name: "Selection" }));
    const name = await panel.findByRole("textbox", { name: "Name" });
    await userEvent.clear(name);
    await userEvent.click(canvas.getByRole("toolbar", { name: "Diagram editing" }));
    await expect(await panel.findByRole("alert")).toHaveTextContent("A name is required.");
    await expect(api.put).not.toHaveBeenCalled();
    await userEvent.type(name, "Gateway");
    const description = panel.getByRole("textbox", { name: /^Description/ });
    await userEvent.type(description, "Edge.");
    await userEvent.click(canvas.getByRole("toolbar", { name: "Diagram editing" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(`${BASE}/elements/el-1`, { description: "Terminates client traffic.Edge.", version: 1 }));
  },
};
export const EditingALinesConnectionInTheSelectionCardStoresItAndKeepsPendingLayoutEdits: Story = {
  beforeEach: () => { spyOn(api, "put").mockResolvedValue(buildConnection({ version: 2, protocol: "HTTP/2" }) as never); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Gateway");
    await userEvent.keyboard("{ArrowRight}");
    await waitFor(() => expect(canvas.getByRole("button", { name: "Save diagram" })).toBeEnabled());
    const panel = await selectLine(canvas);
    await expect(panel.queryByRole("button", { name: "Edit CON-001" })).not.toBeInTheDocument();
    const protocol = await panel.findByLabelText(/^Protocol/);
    await userEvent.clear(protocol);
    await userEvent.type(protocol, "HTTP/2");
    await userEvent.click(panel.getByRole("button", { name: "Save connection" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(`${BASE}/connections/con-1`, { protocol: "HTTP/2", version: 1 }));
    await expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument();
    // The move made before the edit is still waiting to be saved.
    await expect(canvas.getByRole("button", { name: "Save diagram" })).toBeEnabled();
  },
};

/** A line that stands for several connections lists them, each with an Edit button that opens the connection form. */
export const ALineStandingForSeveralConnectionsEditsEachInTheDialog: Story = {
  beforeEach: () => {
    mockArchitectureReads({
      elements: ELEMENTS,
      diagramModel: buildDiagramModel({ connections: [buildConnection(), buildConnection({ id: "con-2", unique_code: "CON-002", name: "Admin traffic" })] }),
    });
    spyOn(api, "put").mockResolvedValue(buildConnection({ version: 2, protocol: "HTTP/2" }) as never);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const panel = await selectLine(canvas, /connection from Gateway to Orders/i);
    await expect(panel.queryByRole("group", { name: "Connection details" })).not.toBeInTheDocument();
    await userEvent.click(panel.getByRole("button", { name: "Edit CON-001" }));
    const dialog = within(await within(document.body).findByRole("dialog"));
    await expect(dialog.getByRole("heading", { name: "Edit Client traffic" })).toBeInTheDocument();
    const protocol = dialog.getByLabelText(/^Protocol/);
    await userEvent.clear(protocol);
    await userEvent.type(protocol, "HTTP/2");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(`${BASE}/connections/con-1`, { protocol: "HTTP/2", version: 1 }));
    await waitFor(() => expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument());
  },
};
const TWO_CONNECTIONS = {
  elements: ELEMENTS,
  diagramModel: buildDiagramModel({ connections: [buildConnection(), buildConnection({ id: "con-2", unique_code: "CON-002", name: "Admin traffic" })] }),
};

/** Choosing a row of a merged line shows that connection's fields in the card, the line's own fields below, and Back returns to the list. */
export const ChoosingAConnectionOfAMergedLineShowsItsFieldsAndBackReturnsToTheList: Story = {
  beforeEach: () => { mockArchitectureReads(TWO_CONNECTIONS); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const panel = await selectLine(canvas, /connection from Gateway to Orders/i);
    await expect(panel.queryByRole("group", { name: "Connection details" })).not.toBeInTheDocument();
    await userEvent.click(panel.getByRole("button", { name: /^CON-002 / }));
    const chosen = within(await panel.findByRole("group", { name: "Chosen connection" }));
    await expect(chosen.getByRole("textbox", { name: /^Name/ })).toHaveValue("Admin traffic");
    await expect(panel.queryByRole("list", { name: "Connections of this line" })).not.toBeInTheDocument();
    // The heading takes the focus, so the change is announced; the line's own fields stay under the connection's.
    await waitFor(() => expect(chosen.getByText("CON-002").closest("p")).toHaveFocus());
    await expect(panel.getByRole("combobox", { name: "Line starts at" })).toBeInTheDocument();
    await expect(panel.getByText(/apply to all 2 connections/)).toBeInTheDocument();
    await expect(panel.getByRole("heading", { name: "Selection" })).toBeInTheDocument();
    await userEvent.click(panel.getByRole("button", { name: "Back to the 2 connections" }));
    await expect(await panel.findByRole("list", { name: "Connections of this line" })).toBeInTheDocument();
    await expect(panel.queryByRole("group", { name: "Chosen connection" })).not.toBeInTheDocument();
    await waitFor(() => expect(panel.getByRole("button", { name: /^CON-002 / })).toHaveFocus());
  },
};

/** The row is a button: Enter chooses it, and Escape on the card (outside a text field) goes back to the list. */
export const AConnectionRowIsChosenFromTheKeyboardAndEscapeGoesBack: Story = {
  beforeEach: () => { mockArchitectureReads(TWO_CONNECTIONS); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const panel = await selectLine(canvas, /connection from Gateway to Orders/i);
    panel.getByRole("button", { name: /^CON-001 / }).focus();
    await userEvent.keyboard("{Enter}");
    const back = await panel.findByRole("button", { name: "Back to the 2 connections" });
    back.focus();
    await userEvent.keyboard("{Escape}");
    await expect(await panel.findByRole("list", { name: "Connections of this line" })).toBeInTheDocument();
    await expect(panel.queryByRole("group", { name: "Chosen connection" })).not.toBeInTheDocument();
  },
};

/** Escape in a text field of the chosen connection leaves the field (focus to the line), not the connection. */
export const EscapeInAFieldOfTheChosenConnectionKeepsTheChoice: Story = {
  beforeEach: () => { mockArchitectureReads(TWO_CONNECTIONS); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const panel = await selectLine(canvas, /connection from Gateway to Orders/i);
    await userEvent.click(panel.getByRole("button", { name: /^CON-001 / }));
    const name = await panel.findByRole("textbox", { name: /^Name/ });
    name.focus();
    await userEvent.keyboard("{Escape}");
    await expect(panel.getByRole("group", { name: "Chosen connection" })).toBeInTheDocument();
  },
};

/** A saved edit to the chosen connection is stored on its own record and the choice stays. */
export const EditingTheChosenConnectionStoresItAndKeepsTheChoice: Story = {
  beforeEach: () => {
    mockArchitectureReads(TWO_CONNECTIONS);
    spyOn(api, "put").mockResolvedValue(buildConnection({ id: "con-2", unique_code: "CON-002", name: "Admin traffic", version: 2, protocol: "HTTP/2" }) as never);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const panel = await selectLine(canvas, /connection from Gateway to Orders/i);
    await userEvent.click(panel.getByRole("button", { name: /^CON-002 / }));
    const protocol = await panel.findByLabelText(/^Protocol/);
    await userEvent.clear(protocol);
    await userEvent.type(protocol, "HTTP/2");
    await userEvent.click(panel.getByRole("button", { name: "Save connection" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(`${BASE}/connections/con-2`, { protocol: "HTTP/2", version: 1 }));
    await expect(panel.getByRole("group", { name: "Chosen connection" })).toBeInTheDocument();
    await expect(panel.getByRole("group", { name: "Connection details" })).toBeInTheDocument();
  },
};

/** Selecting anything else on the canvas ends the choice, so the line opens at its list again. */
export const SelectingAnotherItemEndsTheChoiceOfAConnection: Story = {
  beforeEach: () => { mockArchitectureReads(TWO_CONNECTIONS); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const panel = await selectLine(canvas, /connection from Gateway to Orders/i);
    await userEvent.click(panel.getByRole("button", { name: /^CON-001 / }));
    await panel.findByRole("group", { name: "Chosen connection" });
    await select(canvas, "Gateway");
    await expect(await panel.findByRole("link", { name: "Open element" })).toBeInTheDocument();
    const again = await selectLine(canvas, /connection from Gateway to Orders/i);
    await expect(await again.findByRole("list", { name: "Connections of this line" })).toBeInTheDocument();
    await expect(again.queryByRole("group", { name: "Chosen connection" })).not.toBeInTheDocument();
  },
};

/** A connection shared from another project is chosen like any other but shown read-only; Open names it and goes to its page. */
export const AChosenConnectionOfAnotherProjectIsReadOnlyAndOpenGoesToItsPage: Story = {
  beforeEach: () => {
    mockArchitectureReads({
      elements: ELEMENTS,
      diagramModel: buildDiagramModel({ connections: [buildConnection(), buildConnection({ id: "con-2", unique_code: "CON-002", project_id: "proj-other" })] }),
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const panel = await selectLine(canvas, /connection from Gateway to Orders/i);
    await expect(panel.getByRole("link", { name: "Open CON-001" })).toHaveAttribute("href", expect.stringMatching(/\/connections\/con-1$/));
    await expect(panel.queryByRole("button", { name: "Edit CON-002" })).not.toBeInTheDocument();
    await userEvent.click(panel.getByRole("button", { name: /^CON-002 / }));
    const chosen = within(await panel.findByRole("group", { name: "Chosen connection" }));
    await expect(chosen.queryByRole("textbox")).not.toBeInTheDocument();
    await expect(chosen.getByRole("link", { name: "Open CON-002" })).toHaveAttribute("href", expect.stringMatching(/\/connections\/con-2$/));
  },
};

export const AConnectionSharedFromAnotherProjectHasNoEditButton: Story = {
  beforeEach: () => {
    mockArchitectureReads({
      elements: ELEMENTS,
      diagramModel: buildDiagramModel({ connections: [buildConnection({ project_id: "proj-other" })] }),
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const panel = await selectLine(canvas);
    await expect(panel.getByRole("link", { name: "Open CON-001" })).toBeInTheDocument();
    await expect(panel.queryByRole("button", { name: "Edit CON-001" })).not.toBeInTheDocument();
  },
};

export const ASelectedBoxListsItsPortsAndAddsOneAtOnce: Story = {
  beforeEach: () => { spyOn(api, "post").mockResolvedValue({ id: "port-9", name: "Events", direction: "both", connection_type_id: null } as never); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Gateway");
    const panel = within(await canvas.findByRole("region", { name: "Selection" }));
    await expect(await panel.findByLabelText("Direction of HTTPS API")).toBeInTheDocument();
    await userEvent.type(panel.getByLabelText("Port name", { selector: "input[placeholder='Port name']" }), "Events");
    await userEvent.click(panel.getByRole("button", { name: "Add port" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `${BASE}/elements/el-1/ports`, { name: "Events", direction: "both", connection_type_id: null },
    ));
  },
};

export const TheAddMenuOffersTypeSetupOnlyToSomeoneWhoMayManageTypes: Story = {
  beforeEach: () => { mockArchitectureReads({ elements: ELEMENTS, canManageTypes: false }); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Add to diagram" }));
    await expect(await within(document.body).findByRole("menuitem", { name: "Add note" })).toBeInTheDocument();
    await expect(within(document.body).queryByRole("menuitem", { name: "Set up element types" })).not.toBeInTheDocument();
  },
};

export const TheAddMenuEndsWithASetupEntryForAnArchitectureAdmin: Story = {
  beforeEach: () => { mockArchitectureReads({ elements: ELEMENTS, canManageTypes: true }); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Add to diagram" }));
    const items = await within(document.body).findAllByRole("menuitem");
    await expect(items[items.length - 1]).toHaveAccessibleName("Set up element types");
  },
};

// --- Boundary boxes: the outer connections of a diagram of an element's inside ---

/** Reads the scoped scene (a diagram of Platform's inside with one boundary box) instead of the default diagram. */
function mockBoundaryScene(opts: { realised?: boolean; boundaries?: boolean } = {}) {
  const scene = buildBoundaryScene({ realised: opts.realised });
  mockArchitectureReads({
    elements: scene.elements, connections: scene.model.connections, diagramView: opts.boundaries === false ? { ...scene.view, boundaries: [] } : scene.view,
    diagramModel: scene.model,
  });
}

export const ABoundaryBoxStandsForAnOuterConnectionAndShowsItIsCovered: Story = {
  beforeEach: () => { mockBoundaryScene(); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const box = await canvas.findByLabelText("CON-009, node");
    await expect(box).toHaveTextContent("ELM-008 Cloud · Covered");
    // The connection realising it is drawn from the inner element to the box.
    await expect(await canvas.findByLabelText("Connection from Gateway to CON-009")).toBeInTheDocument();
    await expect(canvas.getByLabelText("Connection from Gateway to Orders")).toBeInTheDocument();
  },
};

export const ABoundaryBoxWithNothingRealisingItReadsNotCovered: Story = {
  beforeEach: () => { mockBoundaryScene({ realised: false }); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByLabelText("CON-009, node")).toHaveTextContent("Not covered");
    await expect(canvas.queryByLabelText("Connection from Gateway to CON-009")).not.toBeInTheDocument();
  },
};

export const SelectingABoundaryBoxListsTheConnectionsThatRealiseIt: Story = {
  beforeEach: () => { mockBoundaryScene(); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "CON-009");
    const panel = within(await canvas.findByRole("region", { name: "Selection" }));
    await expect(panel.getByText("Covered by 1 connection.")).toBeInTheDocument();
    await expect(panel.getByRole("link", { name: "CON-010" })).toBeInTheDocument();
    await expect(panel.getByText(/Outside: ELM-008 Cloud/)).toBeInTheDocument();
    await expect(panel.getByRole("link", { name: "Open connection" })).toBeInTheDocument();
  },
};

export const TheAddMenuOffersTheOuterConnectionsAndDrawsTheChosenOne: Story = {
  beforeEach: () => {
    mockBoundaryScene({ boundaries: false });
    spyOn(api, "put").mockResolvedValue(buildDiagram({ version: 4 }) as never);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByLabelText("CON-009, node")).not.toBeInTheDocument();
    await addFromMenu(canvas, "CON-009 · ELM-008 Cloud");
    await expect(await canvas.findByLabelText("CON-009, node")).toBeInTheDocument();
    // Drawn, the connection is no longer offered; the layout save sends the box with its outer connection.
    await userEvent.click(await canvas.findByRole("button", { name: "Add to diagram" }));
    await expect(within(document.body).queryByRole("menuitem", { name: "CON-009 · ELM-008 Cloud" })).not.toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    await userEvent.click(canvas.getByRole("button", { name: "Save diagram" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      `${BASE}/diagrams/dgm-1/layout`,
      expect.objectContaining({ boundaries: [expect.objectContaining({ connection_id: "con-9" })] }),
    ));
  },
};

export const ConnectToOnABoundaryBoxCreatesAConnectionToTheElementOutsideThatRealisesIt: Story = {
  beforeEach: () => {
    mockBoundaryScene();
    spyOn(api, "post").mockResolvedValue(buildConnection({ id: "con-12", unique_code: "CON-012" }) as never);
    spyOn(api, "put").mockResolvedValue(buildConnection({ id: "con-12", version: 2 }) as never);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "CON-009");
    const panel = within(await canvas.findByRole("region", { name: "Selection" }));
    await userEvent.selectOptions(await panel.findByRole("combobox", { name: /Connect to/ }), "el-2");
    // The outer connection leaves the scope element, so the new one starts at the inner element and ends outside.
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `${BASE}/connections`, expect.objectContaining({ source_element_id: "el-2", target_element_id: "el-8", activate: false }),
    ));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      `${BASE}/connections/con-12/realisations`, expect.objectContaining({ outer_connection_ids: ["con-9"] }),
    ));
    await expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument();
  },
};
export const ALineSetsWhatItRealisesAndTheServersRefusalIsShown: Story = {
  beforeEach: () => {
    mockBoundaryScene({ realised: false });
    spyOn(api, "put").mockRejectedValueOnce(new ApiError(400, "A connection can realise another only when it lies inside the interface the other declares."))
      .mockResolvedValue(buildConnection({ version: 2 }) as never);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const line = await canvas.findByLabelText("Connection from Gateway to Orders");
    line.focus();
    await userEvent.keyboard("{Enter}");
    const panel = within(await canvas.findByRole("region", { name: "Selection" }));
    await userEvent.selectOptions(await panel.findByRole("combobox", { name: "Add outer connection" }), "con-9");
    await expect(await panel.findByRole("alert")).toHaveTextContent("lies inside the interface");
    await userEvent.selectOptions(panel.getByRole("combobox", { name: "Add outer connection" }), "con-9");
    await waitFor(() => expect(api.put).toHaveBeenLastCalledWith(
      `${BASE}/connections/con-11/realisations`, { version: 1, outer_connection_ids: ["con-9"] },
    ));
  },
};

export const TheOutlineListsTheOuterConnectionsWithTheirDirectionAndCoverage: Story = {
  beforeEach: () => { mockBoundaryScene(); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await openTab(canvas, "Outline");
    const table = await canvas.findByRole("table", { name: "Outer connections" });
    await expect(within(table).getByRole("button", { name: "CON-009" })).toBeInTheDocument();
    await expect(within(table).getByText("Output")).toBeInTheDocument();
    await expect(within(table).getByText("Covered")).toBeInTheDocument();
  },
};


/** A pinned thread shows as a marker on the Drawing, and opening it or reading the Comments tab never marks the layout unsaved. */
export const PinnedCommentsShowAsMarkersAndNeverMakeTheLayoutDirty: Story = {
  beforeEach: () => {
    mockArchitectureReads({
      elements: ELEMENTS,
      comments: {
        pins: [buildPin({ id: "p-1", anchor_kind: "node", anchor_key: "el-1", comment_count: 2 })],
        comments: [
          buildComment({ id: "c-1", pin_id: "p-1", body: "Needs rate limiting." }),
          buildComment({ id: "c-2", pin_id: "p-1", author_display_name: "Sam Owner", body: "Added to the backlog.", can_edit: false, can_delete: false }),
          buildComment({ id: "c-3", pin_id: null, body: "General question about scope." }),
        ],
      },
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const marker = await canvas.findByRole("button", { name: /Comment thread by Alex Reviewer, 2 comments/ });
    await userEvent.click(marker);
    const thread = within(await within(document.body).findByRole("dialog", { name: "Comment thread" }));
    await expect(thread.getByText("Needs rate limiting.")).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    await expect(canvas.getByRole("button", { name: "Save diagram" })).toBeDisabled();
    await expect(canvas.queryByText("Unsaved changes.")).toBeNull();
  },
};

/** Comment mode is a toolbar toggle with help; the settings gear carries the viewer's Show comments and Show resolved switches. */
export const CommentModeAndTheDisplaySwitches: Story = {
  beforeEach: () => {
    mockArchitectureReads({
      elements: ELEMENTS,
      comments: { pins: [buildPin({ id: "p-1" })], comments: [buildComment({ id: "c-1", pin_id: "p-1" })] },
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const toggle = await canvas.findByRole("button", { name: "Comment" });
    await expect(toggle).toHaveAttribute("aria-pressed", "false");
    await expect(canvas.queryByRole("button", { name: /^Help: Comment/ })).toBeNull();
    await userEvent.click(toggle);
    await expect(toggle).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(await canvas.findByRole("button", { name: /^Diagram settings/ }));
    const body = within(document.body);
    await userEvent.click(await body.findByRole("switch", { name: "Show comments" }));
    await waitFor(() => expect(canvas.queryByRole("button", { name: /Comment thread/ })).toBeNull());
    await expect(body.getByRole("switch", { name: "Show resolved" })).toBeDisabled();
  },
};

/** The Comments tab lists every comment, marks the pinned ones with what they are anchored to, and filters by state. */
export const TheCommentsTabListsEveryCommentAndFiltersByState: Story = {
  beforeEach: () => {
    mockArchitectureReads({
      elements: ELEMENTS,
      comments: {
        pins: [
          buildPin({ id: "p-1", anchor_kind: "node", anchor_key: "el-1" }),
          buildPin({ id: "p-2", anchor_kind: "node", anchor_key: "gone-box", resolved: true, resolved_by_display_name: "Sam Owner" }),
        ],
        comments: [
          buildComment({ id: "c-1", pin_id: "p-1", body: "Open thread on the gateway." }),
          buildComment({ id: "c-2", pin_id: "p-2", body: "Resolved thread on a removed box." }),
          buildComment({ id: "c-3", pin_id: null, body: "An ordinary comment." }),
        ],
      },
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await openTab(canvas, "Comments");
    await expect(await canvas.findByText("Open thread on the gateway.")).toBeInTheDocument();
    await expect(canvas.getByText("On ELM-001 Gateway")).toBeInTheDocument();
    await expect(canvas.getByText("Its box or line was removed")).toBeInTheDocument();
    await expect(canvas.getAllByText("Pinned")).toHaveLength(2);
    await expect(canvas.getByRole("button", { name: "Pin to diagram" })).toBeInTheDocument();
    await userEvent.selectOptions(canvas.getByLabelText("Show"), "resolved");
    await expect(canvas.queryByText("Open thread on the gateway.")).toBeNull();
    await expect(canvas.getByText("Resolved thread on a removed box.")).toBeInTheDocument();
    await expect(canvas.getByText("An ordinary comment.")).toBeInTheDocument();
  },
};

/** Show on drawing returns to the Drawing tab with the thread open. */
export const ShowOnDrawingOpensTheThreadOnTheCanvas: Story = {
  beforeEach: () => {
    mockArchitectureReads({
      elements: ELEMENTS,
      comments: { pins: [buildPin({ id: "p-1", anchor_kind: "node", anchor_key: "el-1" })], comments: [buildComment({ id: "c-1", pin_id: "p-1", body: "Look at this box." })] },
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await openTab(canvas, "Comments");
    await userEvent.click(await canvas.findByRole("button", { name: "Show on drawing" }));
    await expect(await within(document.body).findByRole("dialog", { name: "Comment thread" })).toBeInTheDocument();
    await expect(await canvas.findByLabelText("Gateway, node")).toBeInTheDocument();
  },
};

/** An archived diagram still takes comments: they are not part of the layout. */
export const AnArchivedDiagramStillTakesComments: Story = {
  beforeEach: () => {
    mockArchitectureReads({ elements: ELEMENTS, diagramView: buildDiagramView({ diagram: buildDiagram({ is_archived: true }) }) });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const toggle = await canvas.findByRole("button", { name: "Comment" });
    await expect(toggle).toBeEnabled();
    await openTab(canvas, "Comments");
    await expect(await canvas.findByRole("textbox", { name: "Add a comment" })).toBeEnabled();
  },
};

/** The names of the actions a Selection card offers, in order (a link or a button of its "Actions" group). */
function actionNames(panel: ReturnType<typeof within>): string[] {
  const group = panel.getByRole("group", { name: "Actions" });
  return [...group.querySelectorAll("a, button")].map((el) => el.getAttribute("aria-label") ?? el.textContent ?? "");
}

/** A box's Selection card offers every action as an icon button with the same name as before, none as a text button. */
export const ABoxSelectionOffersEveryActionAsAnIconButton: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Orders");
    const panel = within(await canvas.findByRole("region", { name: "Selection" }));
    await expect(actionNames(panel)).toEqual([
      "Open element", "Open inside as diagram", "Comment on this box", "Remove from diagram", "Delete element…",
    ]);
    const group = panel.getByRole("group", { name: "Actions" });
    for (const control of group.querySelectorAll("a, button")) await expect(control.textContent?.trim()).toBe("");
    await expect(buttonHeightViolations(canvasElement)).toEqual([]);
  },
};

/** The tooltip of "Open inside as diagram" keeps the explanation the text button used to carry. */
export const TheOpenInsideIconExplainsItselfInItsTooltip: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Orders");
    const panel = within(await canvas.findByRole("region", { name: "Selection" }));
    const inside = panel.getByRole("button", { name: "Open inside as diagram" });
    await userEvent.hover(inside);
    await expect(await within(document.body).findByRole("tooltip")).toHaveTextContent(/own sub-elements/);
  },
};

/** A line's Selection card offers Comment as an icon; a line of several connections has Edit as an icon in each table row. */
export const ALineSelectionOffersItsActionsAsIconButtons: Story = {
  beforeEach: () => {
    mockArchitectureReads({
      elements: ELEMENTS,
      diagramModel: buildDiagramModel({ connections: [buildConnection(), buildConnection({ id: "con-2", unique_code: "CON-002", name: "Admin traffic" })] }),
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const panel = await selectLine(canvas, /connection from Gateway to Orders/i);
    await expect(actionNames(panel)).toEqual(["Comment on this connection"]);
    const edit = panel.getByRole("button", { name: "Edit CON-001" });
    await expect(edit.textContent?.trim()).toBe("");
    await expect(buttonHeightViolations(canvasElement)).toEqual([]);
  },
};

/** A box shared from another owner offers no Edit or Delete, only reading, commenting and taking it off the diagram. */
export const ASharedBoxSelectionOffersNoEditOrDelete: Story = {
  beforeEach: () => {
    mockArchitectureReads({
      elements: ELEMENTS,
      diagramView: buildDiagramView({ nodes: buildDiagramView().nodes.map((n) => (n.element_id === "el-2" ? { ...n, shared: true } : n)) }),
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Orders");
    const panel = within(await canvas.findByRole("region", { name: "Selection" }));
    await expect(actionNames(panel)).toEqual(["Open element", "Open inside as diagram", "Comment on this box", "Remove from diagram"]);
  },
};
