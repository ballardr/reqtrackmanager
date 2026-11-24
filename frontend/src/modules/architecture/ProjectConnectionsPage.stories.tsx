import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, screen, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildUser, withAuth, withRouter, withStatefulAuth, withToast } from "../../testing/storybook-helpers";
import { buildConnection, buildElement, buildFolder, mockArchitectureReads, PROJECT_ID } from "./architectureFixtures";
import { ProjectConnectionsPage } from "./ProjectConnectionsPage";

const CONNECTIONS = [
  buildConnection(),
  buildConnection({ id: "con-2", unique_code: "CON-002", name: "", protocol: "", target_locked: true, target_element_name: "" }),
  buildConnection({ id: "con-3", unique_code: "CON-003", name: "Old feed", status: "retired" }),
];

/** A person who has chosen every optional column, including the two that are off by default. */
const withEveryColumn = withAuth(buildUser({
  id: "user-1",
  ui_preferences: { column_choice_architecture_connections: ["type", "source", "target", "folder", "protocol"] },
}));

const meta: Meta<typeof ProjectConnectionsPage> = {
  title: "Modules/Architecture/ProjectConnectionsPage",
  component: ProjectConnectionsPage,
  decorators: [
    withAuth(buildUser({ id: "user-1" })),
    withRouter(`/projects/${PROJECT_ID}/modules/architecture/connections`, "/projects/:projectId/modules/architecture/connections"),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof ProjectConnectionsPage>;

export const ListShowsEndsAndNamesALockedEndByCodeOnly: Story = {
  decorators: [withEveryColumn],
  beforeEach: () => { mockArchitectureReads({ connections: CONNECTIONS }); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "Connections" });
    const row = within(within(table).getByRole("link", { name: "CON-001" }).closest("tr")!);
    await expect(row.getByText("REST API")).toBeInTheDocument();
    await expect(row.getByText(/ELM-001 Gateway \(HTTPS API\)/)).toBeInTheDocument();
    await expect(row.getByText("HTTPS/1.1")).toBeInTheDocument();
    const locked = within(within(table).getByRole("link", { name: "CON-002" }).closest("tr")!);
    await expect(locked.getByText("(not visible)")).toBeInTheDocument();
    await expect(within(table).queryByRole("link", { name: "CON-003" })).not.toBeInTheDocument();
  },
};

export const NewConnectionPostsTheForm: Story = {
  beforeEach: () => {
    mockArchitectureReads({ connections: CONNECTIONS, elements: [buildElement(), buildElement({ id: "el-2", unique_code: "ELM-002", name: "Orders", ports: [] })] });
    spyOn(api, "post").mockResolvedValue(buildConnection({ id: "con-new" }) as never);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "New connection" }));
    const dialog = within(within(document.body).getByRole("dialog"));
    await userEvent.selectOptions(await dialog.findByLabelText("Source element"), "el-1");
    await userEvent.selectOptions(dialog.getByLabelText("Target element"), "el-2");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/architecture/connections`,
      expect.objectContaining({ source_element_id: "el-1", target_element_id: "el-2", connection_type_id: "ct-1", activate: false }),
    ));
  },
};

/** The Name header orders the connections, an unnamed one last when ascending, and the order follows the second click. */
export const NameHeaderSortsTheList: Story = {
  beforeEach: () => { mockArchitectureReads({ connections: CONNECTIONS }); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "Connections" });
    const codes = () => within(table).getAllByRole("link", { name: /^CON-/ }).map((link) => link.textContent);
    await userEvent.click(within(table).getByRole("button", { name: "Name" }));
    await waitFor(() => expect(codes()).toEqual(["CON-001", "CON-002"]));
    await userEvent.click(within(table).getByRole("button", { name: "Name" }));
    await waitFor(() => expect(codes()).toEqual(["CON-002", "CON-001"]));
  },
};

/** The Folder column shows each connection's path, and choosing a folder in the filter panel narrows the list to it. */
export const FolderColumnAndFilterNarrowTheList: Story = {
  decorators: [withEveryColumn],
  beforeEach: () => {
    mockArchitectureReads({
      connections: [
        buildConnection({ folder_id: "cf-1", folder_path: "Buses" }),
        buildConnection({ id: "con-2", unique_code: "CON-002", name: "Loose", folder_id: null, folder_path: null }),
      ],
      folders: [buildFolder({ id: "cf-1", kind: "connection", name: "Buses", path: "Buses", record_count: 1 })],
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "Connections" });
    await expect(within(within(table).getByRole("link", { name: "CON-001" }).closest("tr")!).getByText("Buses")).toBeInTheDocument();
    await userEvent.click(await canvas.findByRole("button", { name: "Folder Buses" }));
    await waitFor(() => expect(within(table).queryByRole("link", { name: "CON-002" })).not.toBeInTheDocument());
    await expect(within(table).getByRole("link", { name: "CON-001" })).toBeInTheDocument();
  },
};

/** Folder and Protocol are off by default; the column chooser adds them and the reset puts them away again. */
export const FolderAndProtocolAreOptionalAndOffByDefault: Story = {
  decorators: [withStatefulAuth(buildUser({ id: "user-1" }))],
  beforeEach: () => { mockArchitectureReads({ connections: CONNECTIONS }); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "Connections" });
    for (const name of ["Code", "Name", "Type", "Source", "Target", "Status"]) {
      await expect(within(table).getByRole("columnheader", { name })).toBeInTheDocument();
    }
    for (const name of ["Folder", "Protocol"]) {
      await expect(within(table).queryByRole("columnheader", { name })).not.toBeInTheDocument();
    }
    await userEvent.click(canvas.getByRole("button", { name: "Choose columns" }));
    const dialog = await screen.findByRole("dialog", { name: "Columns" });
    await userEvent.click(within(dialog).getByRole("checkbox", { name: "Protocol" }));
    await expect(within(table).getByRole("columnheader", { name: "Protocol" })).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Show the default columns" }));
    await expect(within(table).queryByRole("columnheader", { name: "Protocol" })).not.toBeInTheDocument();
  },
};
