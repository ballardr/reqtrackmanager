import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { buildUser, withAuth, withRouter, withToast } from "../../testing/storybook-helpers";
import {
  buildBaseline, buildBaselineComparison, buildBaselineItem, mockArchitectureReads, PROJECT_ID,
} from "./architectureFixtures";
import { BaselineDetailPage } from "./BaselineDetailPage";

const meta: Meta<typeof BaselineDetailPage> = {
  title: "Modules/Architecture/BaselineDetailPage",
  component: BaselineDetailPage,
  decorators: [
    withAuth(buildUser({ id: "user-1" })),
    withRouter(`/projects/${PROJECT_ID}/modules/architecture/baselines/bl-1`, "/projects/:projectId/modules/architecture/baselines/:baselineId"),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof BaselineDetailPage>;

const OTHERS = [buildBaseline(), buildBaseline({ id: "bl-2", label: "Design baseline", kind: "stage", stage_name: "Design" })];

/** The header says when and by whom it was taken, and each record type has its own card with a back link to the list. */
export const ShowsTheRecordsByType: Story = {
  beforeEach: () => { mockArchitectureReads({ baselines: OTHERS }); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("heading", { name: /Before review/ })).toBeInTheDocument();
    await expect(canvas.getByText(/by Ada Admin/)).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: /Baselines/ })).toHaveAttribute("href", `/projects/${PROJECT_ID}/modules/architecture?tab=baselines`);
    const elements = within(canvas.getByRole("table", { name: "Elements" }));
    await expect(elements.getByText("Gateway")).toBeInTheDocument();
    await expect(elements.getByText("Cloud")).toBeInTheDocument();
    await expect(within(canvas.getByRole("table", { name: "Connections" })).getByText("Gateway to Cloud")).toBeInTheDocument();
    await expect(within(canvas.getByRole("region", { name: "State machine diagrams (0)" })).getByText("None in this baseline.")).toBeInTheDocument();
  },
};

/** A row opens the record as it stood, one line per entry of a list field. */
export const OpeningARecordShowsItsContent: Story = {
  beforeEach: () => { mockArchitectureReads({ baselines: OTHERS, baselineItem: buildBaselineItem() }); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const elements = await canvas.findByRole("table", { name: "Elements" });
    await userEvent.click(within(elements).getByRole("button", { name: "ELM-001" }));
    const dialog = within(await within(document.body).findByRole("dialog"));
    await expect(await dialog.findByText("Terminates clients.")).toBeInTheDocument();
    await expect(dialog.getByText("Type")).toBeInTheDocument();
    await expect(dialog.getByText('{"name":"uplink","direction":"out"}')).toBeInTheDocument();
  },
};

/** Choosing the live model shows what was added, removed and changed, with a list field's entries. */
export const ComparingWithTheLiveModel: Story = {
  beforeEach: () => { mockArchitectureReads({ baselines: OTHERS, baselineComparison: buildBaselineComparison() }); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("table", { name: "Elements" });
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Compare with" }), "live");
    const comparison = within(await canvas.findByLabelText("Comparison result"));
    await expect(await comparison.findByText(/Before review compared with Live model/)).toBeInTheDocument();
    await expect(comparison.getByText("Cache", { exact: false })).toBeInTheDocument();
    await expect(comparison.getByText("Cloud", { exact: false })).toBeInTheDocument();
    await expect(comparison.getByText("Gateway", { selector: "span.text-muted" })).toBeInTheDocument();
    await expect(comparison.getAllByText(/Edge gateway/)).toHaveLength(2);
    await expect(comparison.getByText('{"direction":"in","name":"clients"}')).toBeInTheDocument();
    await expect(comparison.getByText("No differences (1 unchanged).")).toBeInTheDocument();
  },
};

/** The other baselines are offered by name, and the choice is in the address so the comparison can be linked. */
export const OffersTheOtherBaselines: Story = {
  beforeEach: () => { mockArchitectureReads({ baselines: OTHERS }); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("table", { name: "Elements" });
    const select = canvas.getByRole("combobox", { name: "Compare with" });
    await waitFor(() => expect(within(select).getByRole("option", { name: "Design baseline" })).toBeInTheDocument());
    await expect(within(select).queryByRole("option", { name: "Before review" })).not.toBeInTheDocument();
  },
};

/** A baseline that cannot be read says so instead of spinning. */
export const NotFound: Story = {
  beforeEach: () => { mockArchitectureReads({ baselineMissing: true }); },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("Baseline not found.")).toBeInTheDocument();
  },
};
