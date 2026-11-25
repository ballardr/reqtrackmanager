import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { STRESS_TEXT } from "../testing/stressFixtures";
import { CellText } from "./CellText";

/** User text that stays inside its cell: one line with an ellipsis (or a clamp), and a tooltip with the full text only while it is cut. */
const meta: Meta<typeof CellText> = {
  title: "Components/CellText",
  component: CellText,
  decorators: [(Story) => <div style={{ width: 240 }}><Story /></div>],
};
export default meta;

type Story = StoryObj<typeof CellText>;

/** Text that fits shows no ellipsis and no tooltip. */
export const FittingTextHasNoTooltip: Story = {
  args: { children: "Short name" },
  play: async ({ canvasElement }) => {
    const text = canvasElement.querySelector<HTMLElement>(".cell-text")!;
    await expect(text.scrollWidth).toBeLessThanOrEqual(text.clientWidth + 1);
    await userEvent.hover(text);
    await expect(within(document.body).queryByRole("tooltip")).not.toBeInTheDocument();
  },
};

/** A long text is one line cut with an ellipsis, and hovering it shows the whole text. */
export const LongTextIsCutAndShownInFullOnHover: Story = {
  args: { children: STRESS_TEXT.name },
  play: async ({ canvasElement }) => {
    const text = canvasElement.querySelector<HTMLElement>(".cell-text")!;
    await expect(text.getBoundingClientRect().height).toBeLessThan(parseFloat(getComputedStyle(text).lineHeight) * 1.5);
    await expect(getComputedStyle(text).textOverflow).toBe("ellipsis");
    await userEvent.hover(text);
    await expect(await within(document.body).findByRole("tooltip")).toHaveTextContent(STRESS_TEXT.name);
  },
};

/** An unbroken word cannot widen its cell. */
export const AnUnbrokenWordStaysInsideItsCell: Story = {
  args: { children: STRESS_TEXT.word },
  play: async ({ canvasElement }) => {
    const text = canvasElement.querySelector<HTMLElement>(".cell-text")!;
    await expect(text.getBoundingClientRect().width).toBeLessThanOrEqual(240);
    await expect(canvasElement.scrollWidth).toBeLessThanOrEqual(canvasElement.clientWidth + 1);
  },
};

/** `lines` allows a short paragraph before the text is cut, and the cut text still has its tooltip. */
export const AClampKeepsWholeLines: Story = {
  args: { children: STRESS_TEXT.name.repeat(2), lines: 2 },
  play: async ({ canvasElement }) => {
    const text = canvasElement.querySelector<HTMLElement>(".cell-text")!;
    const line = parseFloat(getComputedStyle(text).lineHeight);
    await expect(text.getBoundingClientRect().height).toBeGreaterThan(line * 1.5);
    await expect(text.getBoundingClientRect().height).toBeLessThan(line * 2.5);
    await userEvent.hover(text);
    await waitFor(() => expect(within(document.body).getByRole("tooltip")).toBeInTheDocument());
  },
};

/** Beside a button in a row, the text gives way and the button keeps its size and its line. */
export const GivesWayToAControlBesideIt: Story = {
  render: () => (
    <div className="row" style={{ flexWrap: "nowrap", width: 240 }}>
      <CellText>{STRESS_TEXT.name}</CellText>
      <button className="btn" style={{ flex: "none" }} aria-label="Edit row">Edit</button>
    </div>
  ),
  play: async ({ canvasElement }) => {
    const row = canvasElement.querySelector<HTMLElement>(".row")!.getBoundingClientRect();
    const button = within(canvasElement).getByRole("button", { name: "Edit row" }).getBoundingClientRect();
    const text = canvasElement.querySelector<HTMLElement>(".cell-text")!.getBoundingClientRect();
    await expect(button.right).toBeLessThanOrEqual(row.right + 1);
    await expect(Math.abs((button.top + button.bottom) / 2 - (text.top + text.bottom) / 2)).toBeLessThan(button.height);
  },
};

/** In a table cell a clamped text gives its column way, and a capped one stays narrow whatever its length. */
export const InATableCell: Story = {
  decorators: [(Story) => <div style={{ width: 520 }}><Story /></div>],
  render: () => (
    <table>
      <tbody>
        <tr>
          <td><CellText lines={2}>{STRESS_TEXT.name}</CellText></td>
          <td><CellText lines={2} maxWidth="8rem">{STRESS_TEXT.name}</CellText></td>
          <td>Short</td>
        </tr>
      </tbody>
    </table>
  ),
  play: async ({ canvasElement }) => {
    const table = canvasElement.querySelector("table")!;
    await expect(table.getBoundingClientRect().width).toBeLessThanOrEqual(520 + 1);
    const cells = Array.from(canvasElement.querySelectorAll("td")).map((td) => td.getBoundingClientRect().width);
    await expect(cells[1]).toBeLessThanOrEqual(8 * 16 + 24);
    await expect(cells[0]).toBeGreaterThan(cells[1]);
  },
};

export const DarkTheme: Story = { ...LongTextIsCutAndShownInFullOnHover, globals: { theme: "dark" } };
