import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildRecordColumns } from "../../testing/recordTablesFixtures";
import { expectStressStable, stressText } from "../../testing/stressFixtures";
import { buildUser, withRouter, withStatefulAuth, withToast } from "../../testing/storybook-helpers";
import { TextStress } from "../../testing/TextStress";
import { buildException, EXCEPTION_PROJECT_ID } from "./exceptionFixtures";
import { ProjectExceptionsPage } from "./ProjectExceptionsPage";
import type { TraceabilityException } from "./types";

const ROWS: TraceabilityException[] = [
  buildException(),
  buildException({
    id: "tex-2", unique_code: "TEX-002", title: "Exception awaiting a decision", status: "requested", covers: false,
    no_cover_reason: "not_approved", expires_on: null, decided_at: null, decided_by_name: null,
  }),
];

function mockApis(rows: TraceabilityException[] = ROWS) {
  return spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.endsWith("/records/traceability_exception/columns")) return buildRecordColumns({ label: "Traceability exceptions" });
    if (path.split("?")[0].endsWith("/modules/traceability/exceptions")) return rows;
    if (path.endsWith(`/projects/${EXCEPTION_PROJECT_ID}`)) return { id: EXCEPTION_PROJECT_ID, organization_id: "org-1" };
    if (path.endsWith("/comments") || path.endsWith("/files")) return [];
    throw new Error(`Unmocked GET: ${path}`);
  });
}

const meta: Meta<typeof ProjectExceptionsPage> = {
  title: "Modules/Traceability/ProjectExceptionsPage",
  component: ProjectExceptionsPage,
  decorators: [
    withStatefulAuth(buildUser({ id: "user-1", display_name: "Alex Morgan", ui_preferences: {} })),
    withRouter(`/projects/${EXCEPTION_PROJECT_ID}/modules/traceability/exceptions`, "/projects/:projectId/modules/traceability/exceptions"),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof ProjectExceptionsPage>;

/** Each row shows its state apart from whether it covers the record, links to its page and offers no creation control. */
export const ListsExceptionsWithTheirCover: Story = {
  beforeEach: () => { mockApis(); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "Traceability exceptions" });
    const approved = within(within(table).getByRole("link", { name: "TEX-001" }).closest("tr")!);
    await expect(approved.getByText("Approved")).toBeInTheDocument();
    await expect(approved.getByText("Covering")).toBeInTheDocument();
    await expect(approved.getByText("SW-PERF-001 Respond within one second")).toBeInTheDocument();
    const waiting = within(within(table).getByRole("link", { name: "TEX-002" }).closest("tr")!);
    await expect(waiting.getByText("Requested")).toBeInTheDocument();
    await expect(waiting.getByText("Not approved")).toBeInTheDocument();
    await expect(within(table).getByRole("link", { name: "TEX-001" })).toHaveAttribute(
      "href", `/projects/${EXCEPTION_PROJECT_ID}/modules/traceability/exceptions/tex-1`,
    );
    await expect(canvas.queryByRole("button", { name: /^New/ })).not.toBeInTheDocument();
  },
};

/** "Open only" asks the server for the exceptions awaiting a decision or in force. */
export const OpenOnlyIsAskedOfTheServer: Story = {
  beforeEach: () => { mockApis(); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("table", { name: "Traceability exceptions" });
    await userEvent.click(canvas.getByRole("checkbox", { name: "Open only" }));
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(
      `/api/v1/projects/${EXCEPTION_PROJECT_ID}/modules/traceability/exceptions?open_only=true`,
    ));
  },
};

export const Empty: Story = {
  beforeEach: () => { mockApis([]); },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("No traceability exceptions recorded for this project yet.")).toBeInTheDocument();
  },
};

/** Long and unbroken text in several cells of several rows leaves the table's shape unchanged. */
export const LongText: Story = {
  beforeEach: () => {
    // The first render reads the short rows, the second the long ones.
    let reads = 0;
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.split("?")[0].endsWith("/modules/traceability/exceptions")) {
        const long = reads++ > 0;
        return ROWS.map((row) => ({
          ...row,
          title: stressText(long, row.title),
          rule_name: stressText(long, row.rule_name, "word"),
          record: { ...row.record, label: stressText(long, row.record.label) },
        }));
      }
      if (path.endsWith("/records/traceability_exception/columns")) return buildRecordColumns({ label: "Traceability exceptions" });
      if (path.endsWith(`/projects/${EXCEPTION_PROJECT_ID}`)) return { id: EXCEPTION_PROJECT_ID, organization_id: "org-1" };
      throw new Error(`Unmocked GET: ${path}`);
    });
  },
  render: () => <TextStress width={1100} render={() => <ProjectExceptionsPage />} />,
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getAllByRole("table", { name: "Traceability exceptions" })).toHaveLength(2));
    await expectStressStable(canvasElement);
  },
};
