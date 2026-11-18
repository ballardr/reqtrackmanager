/**
 * Stories: the block diagram editor's Selection card holds its content at every width and never grows past the drawing.
 *
 * The card sits beside the drawing on a wide screen (a narrow column) and under it on a narrow one (the screen's width), so
 * each selection kind (an element with ports and the symbol picker, a line, a note, a leader) is opened at several window
 * widths and nothing in the card may run out of it. A card with a long list scrolls inside itself, up to the drawing's height.
 */
import type { Meta, StoryObj } from "@storybook/react-vite";
import { page } from "vitest/browser";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { expectContainerFits } from "../../testing/containerFits";
import { buildUser, withAuth, withRouter, withThemeProvider, withToast } from "../../testing/storybook-helpers";
import { buildElement, buildPort, mockArchitectureReads, PROJECT_ID } from "./architectureFixtures";
import { DiagramEditorPage } from "./DiagramEditorPage";

/** An element with many ports, some with long names, so its card is long. */
const MANY_PORTS = Array.from({ length: 14 }, (_, index) => buildPort({
  id: `port-${index + 1}`, name: index === 0 ? "Redundant telemetry uplink to the ground segment" : `Port ${index + 1}`,
  direction: index % 3 === 0 ? "in" : index % 3 === 1 ? "out" : "both",
  connection_type_id: "ct-1", connection_type_name: "REST API", sort_order: index,
}));
const ELEMENTS = [
  buildElement({ name: "Gateway", ports: MANY_PORTS }),
  buildElement({ id: "el-2", unique_code: "ELM-002", name: "Orders", ports: [] }),
];

const meta: Meta<typeof DiagramEditorPage> = {
  title: "Modules/Architecture/SelectionCard/Fit",
  component: DiagramEditorPage,
  decorators: [
    withAuth(buildUser({ id: "user-1" })),
    withRouter(`/projects/${PROJECT_ID}/modules/architecture/diagrams/dgm-1`, "/projects/:projectId/modules/architecture/diagrams/:diagramId"),
    withToast(),
    withThemeProvider(),
  ],
  loaders: [async () => { await import("../../components/GraphCanvasView"); return {}; }],
  beforeEach: () => { mockArchitectureReads({ elements: ELEMENTS, canManageTypes: true }); },
};
export default meta;

type Story = StoryObj<typeof DiagramEditorPage>;

/** Selects a box by name (focus then Enter) and returns the Selection card's element. */
async function selectBox(canvas: ReturnType<typeof within>, name: string): Promise<HTMLElement> {
  const node = await canvas.findByLabelText(`${name}, node`);
  node.focus();
  await userEvent.keyboard("{Enter}");
  return canvas.findByRole("region", { name: "Selection" });
}

/** Selects the line between Gateway and Orders and returns the card. */
async function selectLine(canvas: ReturnType<typeof within>): Promise<HTMLElement> {
  // The edge is looked up and focused afresh on each attempt: the diagram re-renders after an edit in the card, which
  // can replace the element or leave the focus in the field, so Enter would not reach the line. Focus is asserted so a
  // failure says which step did not happen.
  await waitFor(async () => {
    const edge = await canvas.findByLabelText("Connection from Gateway to Orders");
    edge.focus();
    expect(document.activeElement, "the line took the focus").toBe(edge);
    await userEvent.keyboard("{Enter}");
    // The previous selection's card is already a "Selection" region, so check that it now shows the line.
    const heading = within(await canvas.findByRole("region", { name: "Selection" })).getByRole("heading", { level: 2 });
    expect(heading, "the card shows the line").not.toHaveTextContent("ELM-001");
  }, { timeout: 5000 });
  return canvas.findByRole("region", { name: "Selection" });
}

/** Adds a note from the Add menu; the new note is the selection. */
async function addNote(canvas: ReturnType<typeof within>): Promise<HTMLElement> {
  await userEvent.click(await canvas.findByRole("button", { name: "Add to diagram" }));
  await userEvent.click(await within(document.body).findByRole("menuitem", { name: "Add note" }));
  return canvas.findByRole("region", { name: "Selection" });
}

/**
 * Opens each kind of selection at a window width and asserts the card holds its content.
 *
 * @param width The window's width in CSS pixels.
 */
function cardFitsAt(width: number): Story {
  return {
    play: async ({ canvasElement }) => {
      await page.viewport(width, 900);
      const canvas = within(canvasElement);
      await expectContainerFits(await selectBox(canvas, "Gateway"), "Selection card (element)");
      await expectContainerFits(await selectLine(canvas), "Selection card (line)");
      const noteCard = await addNote(canvas);
      await expectContainerFits(noteCard, "Selection card (note)");
      await userEvent.click(await canvas.findByRole("button", { name: "Add leader" }));
      await canvas.findByText("Leader 1");
      await expectContainerFits(await canvas.findByRole("region", { name: "Selection" }), "Selection card (leader)");
    },
  };
}

export const CardFits320: Story = cardFitsAt(320);
export const CardFits390: Story = cardFitsAt(390);
export const CardFits520: Story = cardFitsAt(520);
export const CardFits1280: Story = cardFitsAt(1280);

/** The element's Ports list on its own at the widths the card takes: the name, direction and type selects and the remove button are all inside the card. */
export const PortsListFitsTheCard: Story = {
  play: async ({ canvasElement }) => {
    await page.viewport(1280, 900);
    const card = await selectBox(within(canvasElement), "Gateway");
    const ports = within(card).getByLabelText("Port name", { selector: "input[placeholder='Port name']" });
    await expect(ports).toBeInTheDocument();
    for (const control of [
      within(card).getAllByLabelText(/^Direction of /)[0], within(card).getAllByLabelText(/^Connection type of /)[0],
      within(card).getAllByRole("button", { name: "Remove port" })[0],
    ]) {
      const box = control.getBoundingClientRect();
      const cardBox = card.getBoundingClientRect();
      await expect(box.right).toBeLessThanOrEqual(cardBox.right + 1.5);
    }
  },
};

/** A long card is no taller than the drawing and scrolls inside itself; its heading stays in view while it scrolls. */
export const ALongCardIsNoTallerThanTheDrawingAndScrollsInside: Story = {
  play: async ({ canvasElement }) => {
    await page.viewport(1280, 700);
    const canvas = within(canvasElement);
    const card = await selectBox(canvas, "Gateway");
    const drawing = canvasElement.querySelector<HTMLElement>(".react-flow");
    await expect(drawing).not.toBeNull();
    await waitFor(() => expect(card.getBoundingClientRect().height).toBeLessThanOrEqual(drawing!.getBoundingClientRect().height + 1));
    const body = within(card).getByRole("group", { name: "Selection content" });
    await expect(body.scrollHeight).toBeGreaterThan(body.clientHeight);
    body.scrollTop = body.scrollHeight;
    const heading = within(card).getByRole("heading", { level: 2 });
    const cardBox = card.getBoundingClientRect();
    await expect(heading.getBoundingClientRect().top).toBeGreaterThanOrEqual(cardBox.top - 1);
    await expect(heading.getBoundingClientRect().bottom).toBeLessThanOrEqual(cardBox.top + cardBox.height / 2);
    // The row of actions stays at the top of the scrolling area.
    const actions = within(card).getByRole("group", { name: "Actions" });
    await expect(actions.getBoundingClientRect().top).toBeLessThanOrEqual(body.getBoundingClientRect().top + 24);
  },
};

/** A card with little to show (nothing selected) keeps its natural height, well under the drawing's, and has nothing to scroll. */
export const AShortCardKeepsItsNaturalHeight: Story = {
  play: async ({ canvasElement }) => {
    await page.viewport(1280, 900);
    const canvas = within(canvasElement);
    await canvas.findByLabelText("Gateway, node");
    const card = await canvas.findByRole("region", { name: "Selection" });
    const drawing = canvasElement.querySelector<HTMLElement>(".react-flow");
    await expect(card.getBoundingClientRect().height).toBeLessThan(drawing!.getBoundingClientRect().height / 2);
    const body = within(card).getByRole("group", { name: "Selection content" });
    await expect(body.scrollHeight).toBeLessThanOrEqual(body.clientHeight + 1);
  },
};

/** A field that takes the focus when it appears (a box just added) is scrolled into view inside the card, not left below the fold. */
export const ANewBoxesNameFieldIsScrolledIntoViewInsideTheCard: Story = {
  play: async ({ canvasElement }) => {
    await page.viewport(1280, 700);
    const canvas = within(canvasElement);
    const card = await selectBox(canvas, "Gateway");
    const body = within(card).getByRole("group", { name: "Selection content" });
    body.scrollTop = body.scrollHeight;
    const name = within(card).getByRole("textbox", { name: "Name" });
    name.focus();
    await waitFor(() => {
      const box = name.getBoundingClientRect();
      const area = body.getBoundingClientRect();
      expect(box.top).toBeGreaterThanOrEqual(area.top - 1);
      expect(box.bottom).toBeLessThanOrEqual(area.bottom + 1);
    });
  },
};

/** The card is titled with what is selected and its Save button sits on the heading line, so it stays in view while a long card scrolls. */
export const TheTitleNamesTheSelectionAndSaveSitsBesideIt: Story = {
  play: async ({ canvasElement }) => {
    await page.viewport(1280, 700);
    const canvas = within(canvasElement);
    const card = await selectBox(canvas, "Gateway");
    const heading = within(card).getByRole("heading", { level: 2 });
    await expect(heading).toHaveTextContent("ELM-001 Gateway");
    const save = within(card).getByRole("button", { name: "Save element" });
    await expect(save).toBeDisabled();
    // On the heading's line, outside the scrolling content.
    await expect(heading.parentElement).toContainElement(save);
    await expect(within(card).getByRole("group", { name: "Selection content" })).not.toContainElement(save);
    const name = within(card).getByRole("textbox", { name: /^Name/ });
    await userEvent.type(name, " X");
    await expect(save).toBeEnabled();
    // Scrolled to the foot, the heading and Save are still in view.
    const body = within(card).getByRole("group", { name: "Selection content" });
    body.scrollTop = body.scrollHeight;
    const cardBox = card.getBoundingClientRect();
    await expect(save.getBoundingClientRect().top).toBeGreaterThanOrEqual(cardBox.top - 1);
    await expect(save.getBoundingClientRect().bottom).toBeLessThanOrEqual(cardBox.top + cardBox.height / 2);
    // A line's card is titled by its connection or its two ends.
    const line = await selectLine(canvas);
    await expect(within(line).getByRole("heading", { level: 2 })).toHaveTextContent("CON-001");
  },
};
