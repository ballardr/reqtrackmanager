import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api, ApiError } from "../../api/client";
import { buildUser, withAuth, withRouter, withThemeProvider, withToast } from "../../testing/storybook-helpers";
import {
  buildConnection, buildDiagram, buildDiagramModel, buildDiagramView, buildElement, buildModelElement, mockArchitectureReads, PROJECT_ID,
  SYMBOL_SVG,
} from "./architectureFixtures";
import { DiagramEditorPage } from "./DiagramEditorPage";

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
async function openTab(canvas: ReturnType<typeof within>, name: "Drawing" | "Outline" | "Configuration") {
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

export const DrawsBoxesAndLinesFromTheModelData: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("heading", { name: /Platform overview/ })).toBeInTheDocument();
    await expect(await canvas.findByLabelText("Gateway, node")).toBeInTheDocument();
    await expect(canvas.getByLabelText("Orders, node")).toBeInTheDocument();
    await expect(await canvas.findByLabelText("Connection from Gateway to Orders")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Save" })).toBeDisabled();
    await openTab(canvas, "Configuration");
    await expect(await canvas.findByRole("switch", { name: "Security devices" })).toBeChecked();
  },
};

export const MovingABoxEnablesSaveAndSendsTheLayoutWithTheVersion: Story = {
  beforeEach: () => { spyOn(api, "put").mockResolvedValue(buildDiagram({ version: 4 }) as never); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Gateway");
    await userEvent.keyboard("{ArrowRight}{ArrowRight}");
    const save = canvas.getByRole("button", { name: "Save" });
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
    await waitFor(() => expect(canvas.getByRole("button", { name: "Save" })).toBeEnabled());
    await userEvent.click(canvas.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Save" })).toBeDisabled());
    await userEvent.click(canvas.getByRole("button", { name: "Redo" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Save" })).toBeEnabled());
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
    await waitFor(() => expect(canvas.getByRole("button", { name: "Save" })).toBeEnabled());
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1));
    await userEvent.click(await openSettings(canvas));
    await waitFor(() => expect(api.put).toHaveBeenCalledTimes(2));
    // What was saved is the baseline, so nothing is left to save and undoing the move is still possible.
    await waitFor(() => expect(canvas.getByRole("button", { name: "Save" })).toBeDisabled());
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
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.put).toHaveBeenCalled());
    const body = (api.put as unknown as { mock: { calls: [string, { placements: { element_id: string }[] }][] } }).mock.calls[0][1];
    expect(body.placements.map((p) => p.element_id)).not.toContain("el-2");
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
    await waitFor(() => expect(canvas.getByRole("button", { name: "Save" })).toBeEnabled());
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));
    const alert = await canvas.findByRole("alert");
    await expect(alert).toHaveTextContent(/Someone else saved this diagram/);
    await expect(within(alert).getByRole("button", { name: "Reload diagram" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Save" })).toBeDisabled();
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
    await expect(panel.getByRole("link", { name: "CON-001" })).toBeInTheDocument();
    await expect(panel.getByText(/1 connection/)).toBeInTheDocument();
  },
};

/** Selects the line between Gateway and Orders and returns the Selection card. */
async function selectLine(canvas: ReturnType<typeof within>) {
  const edge = await canvas.findByLabelText("Connection from Gateway to Orders");
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
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      `${BASE}/diagrams/dgm-1/layout`,
      expect.objectContaining({
        anchors: [{ source_element_id: "el-1", target_element_id: "el-2", source_point: "bottom", target_point: null }],
      }),
    ));
  },
};

export const ChoosingAutomaticAgainRemovesTheAnchor: Story = {
  beforeEach: () => {
    mockArchitectureReads({
      elements: ELEMENTS,
      diagramView: buildDiagramView({ anchors: [{ source_element_id: "el-1", target_element_id: "el-2", source_point: "top", target_point: null }] }),
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const panel = await selectLine(canvas);
    await expect(panel.getByRole("combobox", { name: "Line starts at" })).toHaveDisplayValue("Top");
    await userEvent.selectOptions(panel.getByRole("combobox", { name: "Line starts at" }), "Automatic (Right)");
    await waitFor(() => expect(canvas.getByRole("button", { name: "Save" })).toBeEnabled());
    await userEvent.click(canvas.getByRole("button", { name: "Undo" }));
    await expect(panel.getByRole("combobox", { name: "Line starts at" })).toHaveDisplayValue("Top");
    await waitFor(() => expect(canvas.getByRole("button", { name: "Save" })).toBeDisabled());
  },
};

export const RemovingABoxDropsTheAnchorsOfItsLines: Story = {
  beforeEach: () => {
    mockArchitectureReads({
      elements: ELEMENTS,
      diagramView: buildDiagramView({ anchors: [{ source_element_id: "el-1", target_element_id: "el-2", source_point: "top", target_point: "bottom" }] }),
    });
    spyOn(api, "put").mockResolvedValue(buildDiagram({ version: 4 }) as never);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Orders");
    await userEvent.click(await canvas.findByRole("button", { name: "Remove from diagram" }));
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));
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
    await expect(canvas.getByRole("button", { name: "Save" })).toBeEnabled();
    await expect(canvas.getByRole("status")).toHaveTextContent("Unsaved changes.");
  },
};

export const ACreatedElementIsPlacedWhereItWasDropped: Story = {
  beforeEach: () => {
    spyOn(api, "post").mockResolvedValue(buildElement({ id: "el-9", unique_code: "ELM-009", name: "Queue worker" }) as never);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await addFromMenu(canvas, "Service");
    const dialog = within(within(document.body).getByRole("dialog"));
    await userEvent.type(await dialog.findByLabelText(/^Name/), "Queue worker");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await expect(await canvas.findByLabelText("Queue worker, node")).toBeInTheDocument();
    await expect(api.post).toHaveBeenCalledWith(
      `${BASE}/elements`, expect.objectContaining({ name: "Queue worker", element_type_id: "et-1", parent_id: null, activate: false }),
    );
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

/** Records the file names of downloads (an anchor click with a `download` name) instead of saving files. */
function captureDownloads(): string[] {
  const names: string[] = [];
  spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { if (this.download) names.push(this.download); });
  return names;
}

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
  await userEvent.click(await within(document.body).findByRole("menuitem", { name: item }));
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
    await expect(await panel.findByRole("link", { name: "CON-001" })).toBeInTheDocument();
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

export const ConnectToStartsAConnectionWithoutDragging: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Gateway");
    const panel = within(await canvas.findByRole("region", { name: "Selection" }));
    const choose = await panel.findByRole("combobox", { name: /Connect to/ });
    // Only the other visible boxes are offered.
    await expect(within(choose).queryByRole("option", { name: /Gateway/ })).not.toBeInTheDocument();
    await userEvent.selectOptions(choose, "el-2");
    const dialog = within(await within(document.body).findByRole("dialog"));
    await expect(dialog.getByRole("heading", { name: "New connection" })).toBeInTheDocument();
  },
};

export const TheDeleteKeyTakesTheSelectedBoxOffTheDiagramOnly: Story = {
  beforeEach: () => { spyOn(api, "delete").mockResolvedValue(undefined as never); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Orders");
    await userEvent.keyboard("{Delete}");
    await waitFor(() => expect(canvas.queryByLabelText("Orders, node")).not.toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "Save" })).toBeEnabled();
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
    await waitFor(() => expect(canvas.getByRole("button", { name: "Save" })).toBeEnabled());
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
    await expect(labels).toEqual(["Service", "Board", "Custom block", "Add existing elements", "Add note"]);
    for (const heading of ["New software element", "New hardware element", "New element", "Other"]) {
      await expect(menu.getByText(heading)).toBeInTheDocument();
    }
    // A type can be dragged onto the canvas as well as chosen.
    await expect(menu.getByRole("menuitem", { name: "Service" })).toHaveAttribute("draggable", "true");
    await expect(menu.getByRole("menuitem", { name: "Add note" })).toHaveAttribute("draggable", "false");
  },
};

export const ChoosingATypeInTheMenuAsksForTheNewElementsName: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await addFromMenu(canvas, "Board");
    const dialog = within(await within(document.body).findByRole("dialog"));
    await expect(dialog.getByRole("heading", { name: "New Board" })).toBeInTheDocument();
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

export const UnsavedEditsAndTheSelectionSurviveAChangeOfTab: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Gateway");
    await userEvent.keyboard("{ArrowRight}");
    await waitFor(() => expect(canvas.getByRole("button", { name: "Save" })).toBeEnabled());
    await openTab(canvas, "Configuration");
    await expect(await canvas.findByText(/unsaved changes; they are kept/)).toBeInTheDocument();
    await openTab(canvas, "Drawing");
    await expect(await canvas.findByLabelText("Gateway, node")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Save" })).toBeEnabled();
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
    await waitFor(() => expect(canvas.getByRole("button", { name: "Save" })).toBeEnabled());
    // Hold the reads that follow a save, so a second move can be made while the stored layout is being read back.
    const spy = api.get as unknown as { getMockImplementation: () => (...args: unknown[]) => Promise<unknown>; mockImplementation: (fn: unknown) => void };
    const original = spy.getMockImplementation();
    let release = () => {};
    const gate = new Promise<void>((resolve) => { release = resolve; });
    spy.mockImplementation(async (...args: unknown[]) => { await gate; return original(...args); });
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.put).toHaveBeenCalled());
    await select(canvas, "Gateway");
    await userEvent.keyboard("{ArrowRight}");
    release();
    await waitFor(() => expect(canvas.getByRole("status")).toHaveTextContent("Unsaved changes."));
    await expect(canvas.getByRole("button", { name: "Save" })).toBeEnabled();
    // Only the second move is unsaved: undoing it returns to what was stored.
    await userEvent.click(canvas.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Save" })).toBeDisabled());
  },
};

export const EditingABoxOpensTheElementFormAndKeepsPendingLayoutEdits: Story = {
  beforeEach: () => { spyOn(api, "put").mockResolvedValue(buildElement({ version: 2, name: "Edge gateway" }) as never); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Gateway");
    await userEvent.keyboard("{ArrowRight}");
    await waitFor(() => expect(canvas.getByRole("button", { name: "Save" })).toBeEnabled());
    await userEvent.click(await canvas.findByRole("button", { name: "Edit element" }));
    const dialog = within(await within(document.body).findByRole("dialog"));
    const name = await dialog.findByLabelText(/^Name/);
    await userEvent.clear(name);
    await userEvent.type(name, "Edge gateway");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      `${BASE}/elements/el-1`, expect.objectContaining({ name: "Edge gateway", version: 1 }),
    ));
    await waitFor(() => expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument());
    // The move made before the edit is still waiting to be saved.
    await expect(canvas.getByRole("button", { name: "Save" })).toBeEnabled();
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
