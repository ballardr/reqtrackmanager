import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { StatusPieChart } from "./StatusPieChart";

const meta: Meta<typeof StatusPieChart> = {
  title: "Components/StatusPieChart",
  component: StatusPieChart,
};
export default meta;

type Story = StoryObj<typeof StatusPieChart>;

export const RequirementsByStatus: Story = {
  args: {
    title: "Requirements by status",
    segments: [
      ["Draft", 8],
      ["Reviewed", 5],
      ["Approved", 12],
      ["Completed", 20],
      ["Archived", 2],
    ],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Requirements by status")).toBeInTheDocument();
    await expect(canvas.getByText("47")).toBeInTheDocument();
    await expect(canvas.getByText("Draft")).toBeInTheDocument();
  },
};

/** Every count zero: must not divide by zero and must still render a
 * legend (mirrors a brand-new project with no requirements yet). */
export const Empty: Story = {
  args: { title: "Change requests", segments: [["Draft", 0]] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getAllByText("0")).toHaveLength(2);
  },
};

/** Clicking a legend row (the dashboard's click-to-filter navigation,
 * UX review) fires `onSegmentClick` with the clicked segment's label. */
export const Clickable: Story = {
  args: {
    title: "Requirements by status",
    segments: [
      ["Draft", 8],
      ["Approved", 12],
    ],
    onSegmentClick: fn(),
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /Approved/ }));
    await expect(args.onSegmentClick).toHaveBeenCalledWith("Approved", 1);
  },
};

/** A legend that lists more items than there are slices: the folded "Other" slice keeps one row per item. */
export const FoldedLegend: Story = {
  args: {
    title: "Total records",
    segments: [
      ["Requirements", 10],
      ["Other", 5],
    ],
    legend: [
      { label: "Requirements", value: 10, segment: 0 },
      { label: "Risks", value: 3, segment: 1 },
      { label: "Decisions", value: 2, segment: 1 },
    ],
    colors: ["var(--color-primary)", "var(--color-text-muted)"],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("15")).toBeInTheDocument();
    await expect(canvas.getByText("Risks")).toBeInTheDocument();
    await expect(canvas.getByText("Decisions")).toBeInTheDocument();
  },
};

const MANY = ["Requirements", "Risks", "Decisions", "Pain points", "Personas", "Stakeholders", "Needs", "Actions"];

/** More legend rows than the limit: the card keeps five and the rest open from "+N more" in a popover that does not move the page. */
export const LongLegendMovesBehindMore: Story = {
  args: {
    title: "Total records",
    segments: MANY.map((label, i) => [label, 20 - i] as [string, number]),
    onSegmentClick: fn(),
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("button", { name: /Needs/ })).toBeNull();
    const before = canvasElement.getBoundingClientRect().height;
    await userEvent.click(canvas.getByRole("button", { name: "+3 more" }));
    const popover = within(document.body).getByRole("dialog");
    await expect(canvasElement.getBoundingClientRect().height).toBe(before);
    await userEvent.click(within(popover).getByRole("button", { name: /Needs/ }));
    await expect(args.onSegmentClick).toHaveBeenCalledWith("Needs", 6);
    await expect(within(document.body).queryByRole("dialog")).toBeNull();
  },
};

/** Hovering a slice says what it is, how many it holds and its share; a folded slice lists what it folds. */
/** The pointer position (viewport px) over slice `index` of a ring drawn with `values`, at the middle of its band. */
function pointOver(canvasElement: HTMLElement, values: number[], index: number): { clientX: number; clientY: number } {
  const total = values.reduce((sum, v) => sum + v, 0);
  const before = values.slice(0, index).reduce((sum, v) => sum + v, 0);
  const turn = ((before + values[index] / 2) / total) * 2 * Math.PI; // clockwise from the top
  const ring = canvasElement.querySelector(".card > div:nth-child(2)")!.getBoundingClientRect();
  return {
    clientX: ring.left + ring.width / 2 + 48 * Math.sin(turn),
    clientY: ring.top + ring.height / 2 - 48 * Math.cos(turn),
  };
}

const ringOf = (canvasElement: HTMLElement) => canvasElement.querySelector(".card > div:nth-child(2)") as HTMLElement;

/** Hovering a slice says what it is, how many it holds and its share; a folded slice lists what it folds. */
export const HoverNamesTheSlice: Story = {
  args: {
    title: "Total records",
    segments: [["Requirements", 10], ["Other", 5]],
    legend: [
      { label: "Requirements", value: 10, segment: 0 },
      { label: "Risks", value: 3, segment: 1 },
      { label: "Decisions", value: 2, segment: 1 },
    ],
  },
  play: async ({ canvasElement }) => {
    const point = pointOver(canvasElement, [10, 5], 1);
    await userEvent.pointer({ target: ringOf(canvasElement), coords: point });
    const tip = await within(document.body).findByText("Other", { selector: "strong" });
    await expect(tip.parentElement).toHaveTextContent("Other: 5 (33%)");
    await expect(tip.parentElement).toHaveTextContent("Risks: 3");
    await expect(tip.parentElement).toHaveTextContent("Decisions: 2");
    // The box sits beside the pointer and has no transition to slide with.
    const box = tip.parentElement!.getBoundingClientRect();
    await expect(Math.abs(box.left - point.clientX)).toBeLessThan(40);
    await expect(Math.abs(box.top - point.clientY)).toBeLessThan(40);
    await expect(getComputedStyle(tip.parentElement!).transitionDuration).toBe("0s");
    // And it stays: re-rendering the chart under a still pointer does not take it away.
    await new Promise((resolve) => setTimeout(resolve, 700));
    await expect(within(document.body).getByRole("tooltip")).toBeInTheDocument();
  },
};

/** The box never outlives the pointer: leaving the slice, moving into the hole or leaving the chart clears it. */
export const HoverBoxGoesAwayWithThePointer: Story = {
  args: { title: "Total records", segments: [["Requirements", 10], ["Risks", 5]] },
  play: async ({ canvasElement }) => {
    const ring = ringOf(canvasElement);
    const box = ring.getBoundingClientRect();
    const tooltips = () => within(document.body).queryAllByRole("tooltip");
    await userEvent.pointer({ target: ring, coords: pointOver(canvasElement, [10, 5], 0) });
    await waitFor(() => expect(tooltips()).toHaveLength(1));
    // Moving on to another slice replaces the box rather than adding one.
    await userEvent.pointer({ target: ring, coords: pointOver(canvasElement, [10, 5], 1) });
    await waitFor(() => expect(within(document.body).getByRole("tooltip")).toHaveTextContent("Risks: 5"));
    await expect(tooltips()).toHaveLength(1);
    // Into the hole of the ring: still inside the chart, but not on a slice.
    await userEvent.pointer({ target: ring, coords: { clientX: box.left + box.width / 2, clientY: box.top + box.height / 2 } });
    await waitFor(() => expect(tooltips()).toHaveLength(0));
    // Back on a slice, then away from the chart altogether.
    await userEvent.pointer({ target: ring, coords: pointOver(canvasElement, [10, 5], 0) });
    await waitFor(() => expect(tooltips()).toHaveLength(1));
    await userEvent.unhover(ring);
    await waitFor(() => expect(tooltips()).toHaveLength(0));
  },
};

export const LightTheme: Story = { ...RequirementsByStatus, globals: { theme: "light" } };
export const DarkTheme: Story = { ...RequirementsByStatus, globals: { theme: "dark" } };
