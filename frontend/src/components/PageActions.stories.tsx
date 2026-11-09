import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { PageActions, PageActionsProvider, PageActionsSlot } from "./PageActions";

const meta: Meta<typeof PageActions> = {
  title: "Components/PageActions",
  component: PageActions,
};
export default meta;

type Story = StoryObj<typeof PageActions>;

/** A section's action lands in the page's title row, beside the page's own actions, not in the section. */
export const RendersInTheTitleRow: Story = {
  render: () => (
    <PageActionsProvider>
      <div className="stack">
        <div className="row" data-testid="title-row">
          <h1 style={{ margin: 0 }}>Organisation</h1>
          <div className="row" style={{ marginLeft: "auto" }}>
            <PageActionsSlot />
            <button className="btn">Reports</button>
          </div>
        </div>
        <section data-testid="section">
          <PageActions>
            <button className="btn">Export</button>
          </PageActions>
          <p>Section content</p>
        </section>
      </div>
    </PageActionsProvider>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const titleRow = canvas.getByTestId("title-row");
    await expect(within(titleRow).getByRole("button", { name: "Export" })).toBeInTheDocument();
    await expect(within(canvas.getByTestId("section")).queryByRole("button", { name: "Export" })).not.toBeInTheDocument();
    const export_ = canvas.getByRole("button", { name: "Export" }).getBoundingClientRect();
    const reports = canvas.getByRole("button", { name: "Reports" }).getBoundingClientRect();
    await expect(Math.abs(export_.top - reports.top)).toBeLessThan(1);
  },
};

/** With no slot on the page, the action stays with the section so a section used on its own still offers it. */
export const FallsBackToInlineWithoutASlot: Story = {
  render: () => (
    <section data-testid="section">
      <PageActions>
        <button className="btn">Export</button>
      </PageActions>
    </section>
  ),
  play: async ({ canvasElement }) => {
    await expect(within(within(canvasElement).getByTestId("section")).getByRole("button", { name: "Export" })).toBeInTheDocument();
  },
};
