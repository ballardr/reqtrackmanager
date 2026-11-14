import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api, ApiError } from "../../api/client";
import { buildComment, buildPin } from "../../testing/recordCommentsFake";
import { buildUser, withAuth, withRouter, withThemeProvider, withToast } from "../../testing/storybook-helpers";
import {
  buildElement, buildState, buildStateMachine, buildStateMachineModel, buildTransition, captureDownloads, mockArchitectureReads, PROJECT_ID,
} from "./architectureFixtures";
import { StateMachineEditorPage } from "./StateMachineEditorPage";

const BASE = `/api/v1/projects/${PROJECT_ID}/modules/architecture`;
const MACHINE = `${BASE}/state-machine-diagrams/smd-1`;

const meta: Meta<typeof StateMachineEditorPage> = {
  title: "Modules/Architecture/StateMachineEditorPage",
  component: StateMachineEditorPage,
  decorators: [
    withAuth(buildUser({ id: "user-1" })),
    withRouter(
      `/projects/${PROJECT_ID}/modules/architecture/state-machine-diagrams/smd-1`,
      "/projects/:projectId/modules/architecture/state-machine-diagrams/:diagramId",
    ),
    withToast(),
    withThemeProvider(),
  ],
  // The canvas is a lazily loaded chunk; fetching it first keeps a cold load from racing the stories' first wait.
  loaders: [async () => { await import("../../components/GraphCanvasView"); return {}; }],
  beforeEach: () => { mockArchitectureReads({ elements: [buildElement()] }); },
};
export default meta;

type Story = StoryObj<typeof StateMachineEditorPage>;

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

/** Opens the "Add to diagram" menu and chooses an entry (the menu is a popover outside the story's canvas). */
async function addFromMenu(canvas: ReturnType<typeof within>, item: string) {
  await userEvent.click(await canvas.findByRole("button", { name: "Add to diagram" }));
  await userEvent.click(await within(document.body).findByRole("menuitem", { name: item }));
}

export const DrawsStatesMarkersAndTransitionsFromTheModel: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("heading", { name: /Gateway modes/ })).toBeInTheDocument();
    await expect(await canvas.findByLabelText("Idle, node")).toBeInTheDocument();
    await expect(canvas.getByLabelText("Running, node")).toBeInTheDocument();
    // The markers are named for their kind and drawn as shapes with no text inside.
    await expect(canvas.getByLabelText("Initial state, node")).toBeInTheDocument();
    await expect(canvas.getByLabelText("Final state, node")).toBeInTheDocument();
    await expect(canvas.getByLabelText("start [ready], connection from Idle to Running")).toBeInTheDocument();
    // A transition from a state to itself is a loop on that state.
    await expect(canvas.getByLabelText("tick / adjust, connection from Running to Running")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Save" })).toBeDisabled();
    // A state shows its entry and exit lines in the box.
    await expect(within(canvas.getByLabelText("Idle, node")).getByText(/entry \/ stop motor/)).toBeInTheDocument();
    await expect(canvas.getByText("Describes", { exact: false })).toBeInTheDocument();
  },
};

export const MovingAStateEnablesSaveAndSendsTheDrawingWithTheVersion: Story = {
  beforeEach: () => { spyOn(api, "put").mockResolvedValue(buildStateMachine({ version: 6 }) as never); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Idle");
    await userEvent.keyboard("{ArrowRight}{ArrowRight}");
    const save = canvas.getByRole("button", { name: "Save" });
    await waitFor(() => expect(save).toBeEnabled());
    await userEvent.click(save);
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      `${MACHINE}/layout`,
      expect.objectContaining({
        version: 5,
        states: expect.arrayContaining([expect.objectContaining({ id: "ste-1", parent_state_id: null }), expect.objectContaining({ id: "ste-2" })]),
        transitions: expect.arrayContaining([expect.objectContaining({ id: "trn-1", source_point: null })]),
      }),
    ));
  },
};

export const UndoReturnsToTheSavedDrawing: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Idle");
    await userEvent.keyboard("{ArrowDown}");
    await waitFor(() => expect(canvas.getByRole("button", { name: "Save" })).toBeEnabled());
    await userEvent.click(canvas.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Save" })).toBeDisabled());
    await userEvent.click(canvas.getByRole("button", { name: "Redo" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Save" })).toBeEnabled());
  },
};

export const AddingAStateOpensItsFormAndCreatesItOnSave: Story = {
  beforeEach: () => { spyOn(api, "post").mockResolvedValue(buildState({ id: "ste-9", unique_code: "STE-009", name: "Fault" }) as never); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await addFromMenu(canvas, "State");
    const dialog = within(await within(document.body).findByRole("dialog"));
    await userEvent.type(dialog.getByLabelText(/^Name/), "Fault");
    await userEvent.type(dialog.getByLabelText("Entry action"), "raise alarm");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `${MACHINE}/states`,
      expect.objectContaining({ version: 5, name: "Fault", kind: "state", entry_action: "raise alarm", parent_state_id: null, width: 160, height: 64 }),
    ));
    await waitFor(() => expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument());
  },
};

export const CancellingTheStateFormCreatesNothing: Story = {
  beforeEach: () => { spyOn(api, "post").mockResolvedValue(buildState() as never); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await addFromMenu(canvas, "State");
    const dialog = within(await within(document.body).findByRole("dialog"));
    await userEvent.type(dialog.getByLabelText(/^Name/), "Never");
    // Closing a form with typed text asks before discarding it.
    await userEvent.click(dialog.getByRole("button", { name: "Close" }));
    await userEvent.click(await within(document.body).findByRole("button", { name: "Discard changes" }));
    await waitFor(() => expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument());
    await expect(api.post).not.toHaveBeenCalled();
  },
};

/** A marker is a shape with no inside: its form takes a name (preset to its kind) and no actions. */
export const AMarkerFormTakesOnlyAName: Story = {
  beforeEach: () => { spyOn(api, "post").mockResolvedValue(buildState({ id: "ste-8", kind: "choice" }) as never); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await addFromMenu(canvas, "Choice");
    const dialog = within(await within(document.body).findByRole("dialog"));
    await expect(dialog.getByLabelText(/^Name/)).toHaveValue("Choice");
    await expect(dialog.queryByLabelText("Entry action")).not.toBeInTheDocument();
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `${MACHINE}/states`, expect.objectContaining({ kind: "choice", width: 36, height: 36 }),
    ));
  },
};

export const ATransitionIsAddedFromTheSelectionCard: Story = {
  beforeEach: () => { spyOn(api, "post").mockResolvedValue(buildTransition({ id: "trn-9" }) as never); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Idle");
    await userEvent.selectOptions(await canvas.findByRole("combobox", { name: "Add transition to" }), "ste-3");
    const dialog = within(await within(document.body).findByRole("dialog"));
    await expect(dialog.getByLabelText(/^From/)).toHaveValue("ste-1");
    await expect(dialog.getByLabelText(/^To/)).toHaveValue("ste-3");
    await userEvent.type(dialog.getByLabelText("Event"), "shutdown");
    await userEvent.type(dialog.getByLabelText("Guard"), "idle for 10 min");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `${MACHINE}/transitions`,
      expect.objectContaining({ version: 5, source_state_id: "ste-1", target_state_id: "ste-3", event: "shutdown", guard: "idle for 10 min" }),
    ));
  },
};

/** Choosing the state itself in the list draws a loop: both ends are the same state. */
export const ALoopIsAddedByChoosingTheStateItself: Story = {
  beforeEach: () => { spyOn(api, "post").mockResolvedValue(buildTransition({ id: "trn-9" }) as never); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Idle");
    await userEvent.selectOptions(await canvas.findByRole("combobox", { name: "Add transition to" }), "ste-1");
    const dialog = within(await within(document.body).findByRole("dialog"));
    await userEvent.type(dialog.getByLabelText("Event"), "retry");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `${MACHINE}/transitions`, expect.objectContaining({ source_state_id: "ste-1", target_state_id: "ste-1", event: "retry" }),
    ));
  },
};

export const EditingAStateStoresOnlyWhatChanged: Story = {
  beforeEach: () => { spyOn(api, "put").mockResolvedValue(buildState({ name: "Standby" }) as never); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Idle");
    await userEvent.click(await canvas.findByRole("button", { name: "Edit state" }));
    const dialog = within(await within(document.body).findByRole("dialog"));
    const name = dialog.getByLabelText(/^Name/);
    await userEvent.clear(name);
    await userEvent.type(name, "Standby");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(`${BASE}/states/ste-1`, { version: 5, name: "Standby" }));
  },
};

export const DeletingAStateNamesWhatGoesWithItAndNeedsItsCode: Story = {
  beforeEach: () => { spyOn(api, "delete").mockResolvedValue({ transitions: 2, links: 1, version: 6 } as never); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Running");
    await userEvent.click(await canvas.findByRole("button", { name: "Delete state…" }));
    const dialog = within(await within(document.body).findByRole("dialog"));
    await expect(await dialog.findByText(/with its 2 transitions and 1 link/)).toBeInTheDocument();
    const confirm = dialog.getByRole("button", { name: "Delete" });
    await expect(confirm).toBeDisabled();
    await userEvent.type(dialog.getByRole("textbox"), "STE-002");
    await userEvent.click(confirm);
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`${BASE}/states/ste-2?version=5`));
  },
};

/** The Delete key asks first, as the Selection card's button does. */
export const TheDeleteKeyAsksBeforeDeletingATransition: Story = {
  beforeEach: () => { spyOn(api, "delete").mockResolvedValue({ version: 6 } as never); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: /^Transition from STE-001 Idle to STE-002 Running/ }).catch(async () => {
      await openTab(canvas, "Outline");
      return canvas.findByRole("button", { name: /^Transition from STE-001 Idle to STE-002 Running/ });
    }));
    await userEvent.click(await canvas.findByRole("button", { name: "Delete transition…" }));
    const dialog = within(await within(document.body).findByRole("dialog"));
    await userEvent.click(dialog.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`${MACHINE}/transitions/trn-1?version=5`));
  },
};

/** Nesting is a drawing edit: the state moves into the frame, the frame grows, and Save sends the new parent. */
export const NestingAStateFromTheSelectionCardIsAnUnsavedDrawingEdit: Story = {
  beforeEach: () => { spyOn(api, "put").mockResolvedValue(buildStateMachine({ version: 6 }) as never); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Idle");
    await userEvent.selectOptions(await canvas.findByRole("combobox", { name: "Inside" }), "ste-2");
    const save = canvas.getByRole("button", { name: "Save" });
    await waitFor(() => expect(save).toBeEnabled());
    await userEvent.click(save);
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      `${MACHINE}/layout`,
      expect.objectContaining({ states: expect.arrayContaining([expect.objectContaining({ id: "ste-1", parent_state_id: "ste-2" })]) }),
    ));
  },
};

export const FindingsAreCountedListedAndSelectTheirState: Story = {
  beforeEach: () => {
    mockArchitectureReads({
      stateMachineModel: buildStateMachineModel({
        diagram: buildStateMachine({ error_count: 1, warning_count: 1 }),
        findings: [
          { severity: "error", code: "initial_incoming", subject: "STE-000", message: "STE-000 is an initial state and has an incoming transition." },
          { severity: "warning", code: "unreachable", subject: "STE-003", message: "STE-003 cannot be reached from the initial state." },
        ],
      }),
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const card = within(await canvas.findByRole("region", { name: "Findings" }));
    await expect(card.getByText("1 error")).toBeInTheDocument();
    await expect(card.getByText("1 warning")).toBeInTheDocument();
    await expect(card.getByText(/has an incoming transition/)).toBeInTheDocument();
    // The header carries the same counts, and a finding's code selects that state.
    await userEvent.click(card.getByRole("button", { name: "STE-003" }));
    await expect(await within(await canvas.findByRole("region", { name: "Selection" })).findByText("STE-003 Final state", { selector: "strong" })).toBeInTheDocument();
    await expect(within(canvas.getByRole("region", { name: "Selection" })).getByText(/cannot be reached/)).toBeInTheDocument();
  },
};

export const ASoundDiagramReportsNoFindings: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const card = within(await canvas.findByRole("region", { name: "Findings" }));
    await expect(card.getByText("No findings.")).toBeInTheDocument();
    await expect(card.getByText("0 errors")).toBeInTheDocument();
  },
};

/** An activation refused for errors shows the server's list, and is not mistaken for a stale save. */
export const ARefusedActivationShowsTheErrorsAndOffersNoReload: Story = {
  beforeEach: () => {
    spyOn(api, "post").mockRejectedValue(new ApiError(409, "This state machine diagram cannot be activated until its errors are resolved: The state machine diagram has no initial state at the top level."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Change status" }));
    await userEvent.click(await within(document.body).findByRole("menuitem", { name: "Move from Draft to Active" }));
    await expect(await canvas.findByText(/cannot be activated until its errors are resolved/)).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Reload state machine diagram" })).not.toBeInTheDocument();
    await expect(api.post).toHaveBeenCalledWith(`${MACHINE}/status`, { version: 5, status: "active" });
  },
};

export const AStaleVersionOffersAReloadInsteadOfOverwriting: Story = {
  beforeEach: () => {
    spyOn(api, "put").mockRejectedValue(new ApiError(409, "This record was changed by someone else. Reload it and apply your change again."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await select(canvas, "Idle");
    await userEvent.keyboard("{ArrowRight}");
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));
    await expect(await canvas.findByRole("button", { name: "Reload state machine diagram" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Save" })).toBeDisabled();
  },
};

export const TheOutlineListsStatesAsATreeAndTransitionsAsATable: Story = {
  beforeEach: () => {
    const nested = buildStateMachineModel().states.map((s) => (s.id === "ste-1" ? { ...s, parent_state_id: "ste-2", parent_state_code: "STE-002" } : s));
    mockArchitectureReads({ stateMachineModel: buildStateMachineModel({ states: nested }) });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await openTab(canvas, "Outline");
    const outline = within(await canvas.findByRole("region", { name: "Outline" }));
    await expect(outline.getByText(/4 states, 4 transitions/)).toBeInTheDocument();
    // Idle is drawn inside Running, so the tree nests it under Running.
    const running = outline.getByRole("button", { name: "STE-002 Running" }).closest("li")!;
    await expect(within(running).getByRole("button", { name: "STE-001 Idle" })).toBeInTheDocument();
    const table = outline.getByRole("table", { name: "Transitions" });
    await expect(within(table).getByText("ready")).toBeInTheDocument();
    await userEvent.click(within(table).getByRole("button", { name: /Transition from STE-001 Idle to STE-002 Running/ }));
    await expect(within(canvas.getByRole("region", { name: "Selection" })).getByText("Edit transition", { selector: "button" })).toBeInTheDocument();
  },
};

export const CommentsAreAnchoredToAStateAndNameIt: Story = {
  beforeEach: () => {
    mockArchitectureReads({
      comments: {
        pins: [buildPin({ id: "p-1", anchor_kind: "node", anchor_key: "ste-1" }), buildPin({ id: "p-2", anchor_kind: "edge", anchor_key: "trn-1" })],
        comments: [buildComment({ id: "c-1", pin_id: "p-1", body: "Why idle first?" }), buildComment({ id: "c-2", pin_id: "p-2", body: "Guard needs a timeout." })],
      },
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await openTab(canvas, "Comments");
    await expect(await canvas.findByText("Why idle first?")).toBeInTheDocument();
    await expect(canvas.getByText("On STE-001 Idle")).toBeInTheDocument();
    await expect(canvas.getByText("On STE-001 → STE-002")).toBeInTheDocument();
  },
};

export const AnArchivedDiagramCannotBeEdited: Story = {
  beforeEach: () => {
    mockArchitectureReads({ stateMachineModel: buildStateMachineModel({ diagram: buildStateMachine({ is_archived: true }) }) });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByLabelText("Idle, node");
    await expect(canvas.getByRole("button", { name: "Add to diagram" })).toBeDisabled();
    await expect(canvas.getByRole("button", { name: "Undo" })).toBeDisabled();
    await select(canvas, "Idle");
    await expect(canvas.queryByRole("button", { name: "Edit state" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Delete state…" })).not.toBeInTheDocument();
  },
};

export const ConfigurationShowsTheElementAndOffersTheEditForm: Story = {
  beforeEach: () => { spyOn(api, "put").mockResolvedValue(buildStateMachine({ name: "Modes" }) as never); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await openTab(canvas, "Configuration");
    await expect(await within(await canvas.findByRole("region", { name: "Details" })).findByRole("link", { name: "ELM-001 Gateway" })).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Edit details" }));
    const dialog = within(await within(document.body).findByRole("dialog"));
    const name = dialog.getByLabelText(/^Name/);
    await userEvent.clear(name);
    await userEvent.type(name, "Modes");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(MACHINE, { version: 5, name: "Modes" }));
  },
};

const PNG_SOURCE = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20" width="40" height="20"><rect width="40" height="20" fill="#0f766e"/></svg>';

/** Answers the export reads with a small SVG and Mermaid text. */
function mockExportReads() {
  spyOn(api, "getForBlob").mockImplementation(async (path: string) => {
    if (path.endsWith("/svg")) return new Blob([PNG_SOURCE], { type: "image/svg+xml" });
    return new Blob(["stateDiagram-v2\n"], { type: "text/plain" });
  });
}

/** Opens the Export menu and chooses an item (the menu is a popover outside the story's canvas). */
async function exportAs(canvas: ReturnType<typeof within>, item: string) {
  await userEvent.click(await canvas.findByRole("button", { name: "Export" }));
  await userEvent.click(await within(document.body).findByRole("menuitem", { name: item }));
}

export const ExportingSvgAndMermaidAsksTheServerForTheStoredDiagram: Story = {
  beforeEach: () => { mockExportReads(); },
  play: async ({ canvasElement }) => {
    const names = captureDownloads();
    const canvas = within(canvasElement);
    await canvas.findByLabelText("Idle, node");
    await exportAs(canvas, "SVG image");
    await waitFor(() => expect(names).toEqual(["SMD-001-gateway-modes.svg"]));
    expect(api.getForBlob).toHaveBeenCalledWith(`${MACHINE}/svg`);
    await exportAs(canvas, "Download Mermaid text");
    await waitFor(() => expect(names).toEqual(["SMD-001-gateway-modes.svg", "SMD-001-gateway-modes.mmd"]));
    expect(api.getForBlob).toHaveBeenCalledWith(`${MACHINE}/mermaid`);
  },
};

export const ExportingPngDrawsTheServersSvgAndCopyingPutsTheMermaidOnTheClipboard: Story = {
  beforeEach: () => {
    mockExportReads();
    Object.defineProperty(navigator, "clipboard", { value: { writeText: fn().mockResolvedValue(undefined) }, configurable: true });
  },
  play: async ({ canvasElement }) => {
    const names = captureDownloads();
    const canvas = within(canvasElement);
    await canvas.findByLabelText("Idle, node");
    await exportAs(canvas, "PNG image");
    await waitFor(() => expect(names).toEqual(["SMD-001-gateway-modes.png"]));
    await exportAs(canvas, "Copy Mermaid text");
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith("stateDiagram-v2\n"));
  },
};

export const ExportingSavesAPendingDrawingFirst: Story = {
  beforeEach: () => {
    mockExportReads();
    spyOn(api, "put").mockResolvedValue(buildStateMachine({ version: 6 }) as never);
  },
  play: async ({ canvasElement }) => {
    const names = captureDownloads();
    const canvas = within(canvasElement);
    await select(canvas, "Idle");
    await userEvent.keyboard("{ArrowRight}");
    await waitFor(() => expect(canvas.getByRole("button", { name: "Save" })).toBeEnabled());
    await exportAs(canvas, "SVG image");
    await waitFor(() => expect(names).toHaveLength(1));
    const put = (api.put as unknown as { mock: { invocationCallOrder: number[] } }).mock.invocationCallOrder[0];
    const read = (api.getForBlob as unknown as { mock: { calls: [string][]; invocationCallOrder: number[] } }).mock;
    expect(put).toBeLessThan(read.invocationCallOrder[read.calls.findIndex(([path]) => path.endsWith("/svg"))]);
  },
};

export const AFailedExportShowsAMessageAndDownloadsNothing: Story = {
  beforeEach: () => {
    spyOn(api, "getForBlob").mockImplementation(async () => { throw new ApiError(500, "Server error"); });
  },
  play: async ({ canvasElement }) => {
    const names = captureDownloads();
    const canvas = within(canvasElement);
    await canvas.findByLabelText("Idle, node");
    await exportAs(canvas, "SVG image");
    await waitFor(() => expect(api.getForBlob).toHaveBeenCalledWith(`${MACHINE}/svg`));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Export" })).toBeEnabled());
    expect(names).toEqual([]);
  },
};
