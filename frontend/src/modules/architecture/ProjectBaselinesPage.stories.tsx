import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../../api/client";
import { requiredCaptions } from "../../testing/requiredMarkers";
import { buildUser, withAuth, withRouter, withToast } from "../../testing/storybook-helpers";
import { buildBaseline, mockArchitectureReads, PROJECT_ID } from "./architectureFixtures";
import { ProjectBaselinesPage } from "./ProjectBaselinesPage";

const BASELINES = [
  buildBaseline(),
  buildBaseline({ id: "bl-2", kind: "stage", label: "Design baseline", stage_name: "Design", created_by_name: "Sam Stage", item_counts: { requirement: 2, architecture_element: 5 } }),
  buildBaseline({ id: "bl-3", label: "Requirements only", item_counts: { requirement: 3 } }),
];

const meta: Meta<typeof ProjectBaselinesPage> = {
  title: "Modules/Architecture/ProjectBaselinesPage",
  component: ProjectBaselinesPage,
  decorators: [
    withAuth(buildUser({ id: "user-1" })),
    withRouter(`/projects/${PROJECT_ID}/modules/architecture?tab=baselines`, "/projects/:projectId/modules/architecture"),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof ProjectBaselinesPage>;

/** The list shows each baseline's kind, stage and the count of architecture records only; a baseline with none is not listed. */
export const ListsBaselinesThatHoldArchitecture: Story = {
  beforeEach: () => { mockArchitectureReads({ baselines: BASELINES }); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "Baselines" });
    const manual = within(within(table).getByRole("link", { name: "Before review" }).closest("tr")!);
    await expect(manual.getByText("Manual")).toBeInTheDocument();
    await expect(manual.getByText("Ada Admin")).toBeInTheDocument();
    await expect(manual.getByText("4")).toBeInTheDocument();
    const stage = within(within(table).getByRole("link", { name: "Design baseline" }).closest("tr")!);
    await expect(stage.getByText("Stage")).toBeInTheDocument();
    await expect(stage.getByText("Design")).toBeInTheDocument();
    await expect(within(table).queryByRole("link", { name: "Requirements only" })).not.toBeInTheDocument();
    await expect(within(table).getByRole("link", { name: "Before review" })).toHaveAttribute(
      "href", `/projects/${PROJECT_ID}/modules/architecture/baselines/bl-1`,
    );
  },
};

/** The Kind filter narrows the list. */
export const KindFilterNarrowsTheList: Story = {
  beforeEach: () => { mockArchitectureReads({ baselines: BASELINES }); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "Baselines" });
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Kind" }), "stage");
    await waitFor(() => expect(within(table).queryByRole("link", { name: "Before review" })).not.toBeInTheDocument());
    await expect(within(table).getByRole("link", { name: "Design baseline" })).toBeInTheDocument();
  },
};

/** A header click orders the list, with the sort in the address. */
export const NameHeaderSortsTheList: Story = {
  beforeEach: () => { mockArchitectureReads({ baselines: BASELINES }); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "Baselines" });
    await userEvent.click(within(table).getByRole("button", { name: "Name" }));
    await waitFor(() => expect(within(table).getAllByRole("link").map((link) => link.textContent)).toEqual(["Before review", "Design baseline"]));
    await userEvent.click(within(table).getByRole("button", { name: "Name" }));
    await waitFor(() => expect(within(table).getAllByRole("link").map((link) => link.textContent)).toEqual(["Design baseline", "Before review"]));
  },
};

/** Taking a baseline sends the name with the architecture types only and reloads the list. */
export const TakeBaselineSendsTheNameAndTheArchitectureTypes: Story = {
  beforeEach: () => { mockArchitectureReads({ baselines: BASELINES }); },
  play: async ({ canvasElement }) => {
    const post = spyOn(api, "post").mockResolvedValue(buildBaseline({ id: "bl-9" }) as never);
    const canvas = within(canvasElement);
    await canvas.findByRole("table", { name: "Baselines" });
    await userEvent.click(canvas.getByRole("button", { name: "Take baseline" }));
    const dialog = within(await within(document.body).findByRole("dialog"));
    await expect(requiredCaptions(within(document.body).getByRole("dialog"))).toEqual(["Name"]);
    await expect(dialog.getByRole("button", { name: "Take baseline" })).toBeDisabled();
    await userEvent.type(dialog.getByRole("textbox", { name: /Name/ }), "  Release 1  ");
    await userEvent.click(dialog.getByRole("button", { name: "Take baseline" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/baselines`,
      { label: "Release 1", item_types: ["architecture_element", "architecture_connection", "architecture_diagram", "architecture_state_machine_diagram"] },
    ));
    await waitFor(() => expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument());
  },
};

/** A refusal (no Architect role) is shown in the dialog, which stays open. */
export const RefusalIsShownInTheDialog: Story = {
  beforeEach: () => { mockArchitectureReads({ baselines: BASELINES }); },
  play: async ({ canvasElement }) => {
    spyOn(api, "post").mockRejectedValue(new ApiError(403, "Insufficient permissions to take a baseline."));
    const canvas = within(canvasElement);
    await canvas.findByRole("table", { name: "Baselines" });
    await userEvent.click(canvas.getByRole("button", { name: "Take baseline" }));
    const dialog = within(await within(document.body).findByRole("dialog"));
    await userEvent.type(dialog.getByRole("textbox", { name: /Name/ }), "Release 1");
    await userEvent.click(dialog.getByRole("button", { name: "Take baseline" }));
    await expect(await dialog.findByText("Insufficient permissions to take a baseline.")).toBeInTheDocument();
  },
};

/** With no baseline holding architecture records the list says so. */
export const EmptyState: Story = {
  beforeEach: () => { mockArchitectureReads({ baselines: [] }); },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("No baselines hold architecture records yet.")).toBeInTheDocument();
  },
};
