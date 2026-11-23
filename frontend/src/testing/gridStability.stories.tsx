/**
 * Stories that pin `gridStability` itself: a tidy grid passes and grids built to
 * break each rule (a track sized by its text, a cell that wraps its controls
 * away) fail, so the guard cannot silently stop detecting a defect.
 */
import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";
import type { ReactNode } from "react";

import { gridLayout, layoutChanges } from "./gridStability";
import { STRESS_TEXT, stressText } from "./stressFixtures";
import { TextStress } from "./TextStress";

const meta: Meta = { title: "Testing/gridStability" };
export default meta;

type Story = StoryObj;

/** A grid of two text tracks and an actions track, with the given first-track definition. */
function Grid({ columns, children }: { columns: string; children: ReactNode }) {
  return <div style={{ display: "grid", gridTemplateColumns: columns, columnGap: 8, alignItems: "start" }} className="definition-grid">{children}</div>;
}

const measure = (element: Element | null) => gridLayout(element ?? undefined);

/** A grid whose tracks are bounded and whose text is clipped by its cell passes every rule, with long text too. */
export const ATidyGridPasses: Story = {
  render: () => (
    <TextStress
      width={600}
      render={(long) => (
        <Grid columns="minmax(0, 1fr) minmax(0, 2fr) max-content">
          <div style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{stressText(long, "Name")}</div>
          <div style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{stressText(long, "Summary", "summary")}</div>
          <button className="btn">Edit</button>
        </Grid>
      )}
    />
  ),
  play: async ({ canvasElement }) => {
    const short = measure(canvasElement.querySelector('[data-stress="short"]'));
    const long = measure(canvasElement.querySelector('[data-stress="long"]'));
    await expect(short.violations).toEqual([]);
    await expect(long.violations).toEqual([]);
    await expect(layoutChanges(short.grids, long.grids)).toEqual([]);
  },
};

/** Rule 1: a cell that starts somewhere no column starts is reported. */
export const RuleOneAnOffsetCellIsReported: Story = {
  render: () => (
    <div style={{ width: 600 }}>
      <Grid columns="1fr 1fr">
        <div>One</div>
        <div style={{ marginLeft: 40 }}>Two</div>
      </Grid>
    </div>
  ),
  play: async ({ canvasElement }) => {
    const { violations } = measure(canvasElement);
    await expect(violations.some((v) => v.includes("is no column's left edge"))).toBe(true);
  },
};

/** Rule 2: the Connection Types defect: text beside a control wraps, and the control drops to a line of its own under the name field. */
export const RuleTwoAWrappedControlIsReported: Story = {
  render: () => (
    <div style={{ width: 600 }}>
      <Grid columns="minmax(0, 1fr) max-content">
        <input className="input" aria-label="Name" defaultValue="Name" />
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center", width: 200 }}>
          <span>{STRESS_TEXT.name}</span>
          <button className="btn" aria-label="Edit row">Edit</button>
        </div>
      </Grid>
    </div>
  ),
  play: async ({ canvasElement }) => {
    const { violations } = measure(canvasElement);
    await expect(violations.some((v) => v.includes('control "Edit row" is on a second line of its row'))).toBe(true);
  },
};

/** Rule 2 (controls stacked in a row): a button below another button of the same row is reported. */
export const RuleTwoAControlBelowAnotherIsReported: Story = {
  render: () => (
    <div style={{ width: 400 }}>
      <Grid columns="1fr max-content">
        <div>Name</div>
        <div style={{ display: "flex", flexDirection: "column" }}>
          <button className="btn" aria-label="Edit row">Edit</button>
          <button className="btn" aria-label="Delete row">Delete</button>
        </div>
      </Grid>
    </div>
  ),
  play: async ({ canvasElement }) => {
    const { violations } = measure(canvasElement);
    await expect(violations.some((v) => v.includes("is on a second line of its row"))).toBe(true);
  },
};

/** Rule 3: a long unbroken word in a cell that does not clip it is reported, as is the overflow it causes. */
export const RuleThreeAnUnclippedWordIsReported: Story = {
  render: () => (
    <div style={{ width: 300 }}>
      <Grid columns="minmax(0, 1fr) minmax(0, 1fr)">
        <div>{STRESS_TEXT.word}</div>
        <div>Short</div>
      </Grid>
    </div>
  ),
  play: async ({ canvasElement }) => {
    const { violations } = measure(canvasElement);
    await expect(violations.some((v) => v.includes("wide in a") || v.includes("sticks out"))).toBe(true);
  },
};

/** Rule 4: a track sized by its text changes width when the text is long, which is reported. */
export const RuleFourATrackSizedByTextIsReported: Story = {
  render: () => (
    <TextStress
      width={600}
      render={(long) => (
        <Grid columns="max-content minmax(0, 1fr)">
          <div>{stressText(long, "Name", "summary")}</div>
          <div>Other</div>
        </Grid>
      )}
    />
  ),
  play: async ({ canvasElement }) => {
    const short = measure(canvasElement.querySelector('[data-stress="short"]'));
    const long = measure(canvasElement.querySelector('[data-stress="long"]'));
    await expect(layoutChanges(short.grids, long.grids).some((m) => m.includes("column 1"))).toBe(true);
  },
};

/** Rule 4: a table that has to scroll sideways only because of its text is reported. */
export const RuleFourLongTextThatMakesATableScrollIsReported: Story = {
  render: () => (
    <TextStress
      width={300}
      render={(long) => (
        <div style={{ overflowX: "auto" }}>
          <table>
            <tbody>
              <tr><td>{stressText(long, "Name", "word")}</td><td>Other</td></tr>
            </tbody>
          </table>
        </div>
      )}
    />
  ),
  play: async ({ canvasElement }) => {
    const short = measure(canvasElement.querySelector('[data-stress="short"]'));
    const long = measure(canvasElement.querySelector('[data-stress="long"]'));
    await expect(layoutChanges(short.grids, long.grids).some((m) => m.includes("scroll sideways"))).toBe(true);
  },
};

/** A row layout whose last control sits at a different place from the row above is reported. */
export const RowControlsThatDoNotLineUpAreReported: Story = {
  render: () => (
    <ul style={{ width: 400, listStyle: "none", padding: 0 }}>
      <li data-stress-row style={{ display: "flex", justifyContent: "space-between" }}><span>One</span><button className="btn">Edit</button></li>
      <li data-stress-row style={{ display: "flex", justifyContent: "flex-start" }}><span>Two</span><button className="btn">Edit</button></li>
    </ul>
  ),
  play: async ({ canvasElement }) => {
    const { violations } = measure(canvasElement);
    await expect(violations.some((v) => v.includes("its last control ends at"))).toBe(true);
  },
};
