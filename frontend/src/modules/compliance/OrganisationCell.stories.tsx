import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import { expectStressStable, stressText } from "../../testing/stressFixtures";
import { TextStress } from "../../testing/TextStress";
import { OrganisationCell, OrganisationHeader, OrganisationLabel } from "./OrganisationCell";

/** How a Compliance status row states its organisation: a column of a table, or the label that leads a sentence-style item. */
const meta: Meta = { title: "Compliance/OrganisationCell" };
export default meta;

type Story = StoryObj;

/** A long organisation name and an unbroken word stay inside the Organisation column and keep the other columns in line; the label keeps its fixed width. */
export const LongText: Story = {
  render: () => (
    <TextStress
      width={640}
      render={(long) => (
        <>
          <table>
            <thead>
              <tr><th>Standard</th><OrganisationHeader show /><th>Status</th></tr>
            </thead>
            <tbody>
              <tr><td>ISO 27001</td><OrganisationCell show name={stressText(long, "Acme Corp")} /><td>Compliant</td></tr>
              <tr><td>SOC 2</td><OrganisationCell show name={stressText(long, "Beta Ltd", "word")} /><td>In progress</td></tr>
            </tbody>
          </table>
          <ul style={{ listStyle: "none", padding: 0 }}>
            <li><OrganisationLabel show name={stressText(long, "Acme Corp")} />Project one</li>
            <li><OrganisationLabel show name={stressText(long, "Beta Ltd", "word")} />Project two</li>
          </ul>
        </>
      )}
    />
  ),
  play: async ({ canvasElement }) => {
    await expectStressStable(canvasElement);
    const labels = Array.from(canvasElement.querySelectorAll<HTMLElement>('[data-stress="long"] .org-cell--label'));
    await expect(new Set(labels.map((label) => Math.round(label.getBoundingClientRect().width))).size).toBe(1);
  },
};

/** With one organisation read, the column and the label draw nothing. */
export const SingleOrganisationShowsNothing: Story = {
  render: () => (
    <table>
      <thead><tr><th>Standard</th><OrganisationHeader show={false} /></tr></thead>
      <tbody><tr><td>ISO 27001</td><OrganisationCell show={false} name="Acme Corp" /></tr></tbody>
    </table>
  ),
  play: async ({ canvasElement }) => {
    await expect(canvasElement.querySelectorAll("th")).toHaveLength(1);
    await expect(canvasElement.querySelectorAll("td")).toHaveLength(1);
  },
};
