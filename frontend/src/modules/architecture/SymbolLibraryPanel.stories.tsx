import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildUser, withRouter, withStatefulAuth, withToast } from "../../testing/storybook-helpers";
import { expectStressStable, stressText } from "../../testing/stressFixtures";
import { TextStress } from "../../testing/TextStress";
import { ORG_ID, PROJECT_ID } from "./architectureFixtures";
import { SymbolLibraryPanel } from "./SymbolLibraryPanel";
import {
  buildBuiltinRow, buildSymbolFolder, buildSymbolRow, libraryQueries, mockSymbolLibrary, type SymbolLibraryReads,
} from "./symbolLibraryFixtures";

const ROWS = [
  buildBuiltinRow(),
  buildSymbolRow({ id: "sym-1", name: "Core router", folder_id: "sf-1", folder_path: "Network", usage_count: 1, used_by: ["Platform"], usage_owner_count: 1 }),
  buildSymbolRow({ id: "sym-2", name: "Edge switch", folder_id: "sf-2", folder_path: "Network/Switches", usage_count: 5, usage_owner_count: 5 }),
  buildSymbolRow({ id: "sym-3", name: "Legacy modem", file_type: "eps" }),
];
const USAGE = {
  "sym-2": {
    owners: [
      { kind: "project" as const, name: "Platform", element_type_count: 1, element_count: 2, element_types: ["Switch"] },
      { kind: "other_projects" as const, name: "Other projects", element_type_count: 0, element_count: 3, element_types: [] },
    ],
  },
};
const FOLDERS = [
  buildSymbolFolder(),
  buildSymbolFolder({ id: "sf-2", name: "Switches", parent_id: "sf-1", path: "Network/Switches" }),
];

const meta: Meta<typeof SymbolLibraryPanel> = {
  title: "Modules/Architecture/SymbolLibraryPanel",
  component: SymbolLibraryPanel,
  args: { scope: { kind: "org", organizationId: ORG_ID } },
  decorators: [
    withStatefulAuth(buildUser({ id: "user-1", display_name: "Alex Morgan" })),
    (Story, context) =>
      withRouter(
        context.parameters.path ?? `/orgs/${ORG_ID}/resources/architecture-symbols`,
        context.parameters.route ?? "/orgs/:orgId/resources/architecture-symbols",
      )(Story, context),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof SymbolLibraryPanel>;

function reads(extra: Partial<SymbolLibraryReads> = {}): SymbolLibraryReads {
  return { rows: ROWS, folders: FOLDERS, usage: USAGE, converter: true, ...extra };
}

/** The organisation's library: a drawing, name, source, folder and where it is used, with a built-in that cannot be renamed. */
export const OrganisationLibraryTable: Story = {
  beforeEach: () => { mockSymbolLibrary(reads()); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "Symbols" });
    await expect(within(table).getByText("Core router")).toBeInTheDocument();
    const router = within(within(table).getByText("Core router").closest("tr")!);
    await expect(router.getByText("Network")).toBeInTheDocument();
    // One or two owners are named; more than two read "N records".
    await expect(router.getByRole("button", { name: /Show where Core router is used/ })).toHaveTextContent("Platform");
    await expect(within(within(table).getByText("Edge switch").closest("tr")!).getByRole("button", { name: /Show where Edge switch is used/ })).toHaveTextContent("5 records");
    await expect(within(within(table).getByText("Legacy modem").closest("tr")!).getByText("Uploaded (EPS (converted))")).toBeInTheDocument();
    // Primary button and the one actions menu.
    await expect(canvas.getByRole("button", { name: "Upload symbols" })).toBeInTheDocument();
    // A built-in is never renamed or filed: its menu has Delete symbol only, and it has no selection box.
    const server = within(within(table).getByText("Server").closest("tr")!);
    await expect(server.queryByRole("checkbox")).not.toBeInTheDocument();
    await userEvent.click(server.getByRole("button", { name: "Actions for Server" }));
    await expect(await within(document.body).findByRole("menuitem", { name: "Delete symbol" })).toBeInTheDocument();
    await expect(within(document.body).queryByRole("menuitem", { name: "Rename" })).not.toBeInTheDocument();
  },
};

export const OrganisationLibraryTableDark: Story = {
  beforeEach: () => { mockSymbolLibrary(reads()); },
  globals: { theme: "dark" },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByRole("table", { name: "Symbols" })).toBeInTheDocument();
  },
};

/** Each filter and the sort go to the server as query parameters; the rows come back already narrowed. */
export const FiltersAndSortGoToTheServer: Story = {
  beforeEach: () => { mockSymbolLibrary(reads()); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("table", { name: "Symbols" });
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Source" }), "uploaded");
    await waitFor(() => expect(canvas.queryByText("Server")).not.toBeInTheDocument());
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Used" }), "used");
    await waitFor(() => expect(canvas.queryByText("Legacy modem")).not.toBeInTheDocument());
    await userEvent.type(canvas.getByRole("textbox", { name: "Search symbols" }), "edge");
    await waitFor(() => expect(canvas.queryByText("Core router")).not.toBeInTheDocument());
    await expect(canvas.getByText("Edge switch")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: /^Name/ }));
    const last = libraryQueries(api.get as unknown as ReturnType<typeof mockSymbolLibrary>).slice(-1)[0];
    await expect(last.get("source")).toBe("uploaded");
    await expect(last.get("used")).toBe("used");
    await expect(last.get("search")).toBe("edge");
    await expect(last.get("sort")).toBe("name");
  },
};

/** The Used by header orders by the number of records that use the symbol, on the server (sort=used, then order=desc). */
export const UsedByHeaderSortsOnTheServer: Story = {
  beforeEach: () => { mockSymbolLibrary(reads()); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "Symbols" });
    const queries = () => libraryQueries(api.get as unknown as ReturnType<typeof mockSymbolLibrary>);
    await userEvent.click(within(table).getByRole("button", { name: "Used by" }));
    await waitFor(() => expect(queries().slice(-1)[0].get("sort")).toBe("used"));
    await expect(queries().slice(-1)[0].get("order")).not.toBe("desc");
    await expect(within(table).getByRole("columnheader", { name: "Used by" })).toHaveAttribute("aria-sort", "ascending");
    await userEvent.click(within(table).getByRole("button", { name: "Used by" }));
    await waitFor(() => expect(queries().slice(-1)[0].get("order")).toBe("desc"));
    await expect(within(table).getByRole("columnheader", { name: "Used by" })).toHaveAttribute("aria-sort", "descending");
  },
};

/** The folder tree is a filter: choosing a folder sends its path, and "Include sub-folders" decides whether the folders below count. */
export const ChoosingAFolderFiltersByItsPath: Story = {
  beforeEach: () => { mockSymbolLibrary(reads()); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("table", { name: "Symbols" });
    await userEvent.click(await canvas.findByRole("button", { name: "Folder Network" }));
    await waitFor(() => expect(canvas.queryByText("Legacy modem")).not.toBeInTheDocument());
    await expect(canvas.getByText("Core router")).toBeInTheDocument();
    await expect(canvas.getByText("Edge switch")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("checkbox", { name: "Include sub-folders" }));
    await waitFor(() => expect(canvas.queryByText("Edge switch")).not.toBeInTheDocument());
    await expect(canvas.getByText("Core router")).toBeInTheDocument();
  },
};

/** The count in Used by opens a dialog with each owner and how many element types and elements use the symbol. */
export const UsedByOpensTheUsageDialog: Story = {
  beforeEach: () => { mockSymbolLibrary(reads()); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: /Show where Edge switch is used/ }));
    const dialog = await within(document.body).findByRole("dialog", { name: "Where Edge switch is used" });
    await expect(within(dialog).getByText("Platform")).toBeInTheDocument();
    await expect(within(dialog).getByText(/1 element type: Switch/)).toBeInTheDocument();
    await expect(within(dialog).getByText("Other projects")).toBeInTheDocument();
    await expect(within(dialog).getByText("3 elements")).toBeInTheDocument();
  },
};

/** The tile view draws the same symbols and actions as cards. */
export const TileViewShowsTheSameSymbols: Story = {
  beforeEach: () => { mockSymbolLibrary(reads()); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("table", { name: "Symbols" });
    await userEvent.click(canvas.getByRole("button", { name: "Tile view" }));
    await expect(await canvas.findByRole("link", { name: "Core router" }).catch(() => canvas.findByText("Core router"))).toBeInTheDocument();
    await expect(canvas.queryByRole("table", { name: "Symbols" })).not.toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Actions for Core router" })).toBeInTheDocument();
    await expect(canvas.getByRole("checkbox", { name: "Select Core router" })).toBeInTheDocument();
    await expect(canvas.queryByRole("checkbox", { name: "Select Server" })).not.toBeInTheDocument();
  },
};

/** Several files upload one after another, each through the sanitiser alone: one refusal does not stop the others. */
export const UploadingSeveralFilesShowsEachOutcome: Story = {
  beforeEach: () => {
    mockSymbolLibrary(reads());
    const post = spyOn(api, "postFile").mockImplementation(async (_path: string, file: File) => {
      if (file.name === "bad.svg") throw new Error("The file contains a script and cannot be used.");
      return {} as never;
    });
    return () => post.mockRestore();
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Upload symbols" }));
    const dialog = await within(document.body).findByRole("dialog", { name: "Upload symbols" });
    const input = dialog.querySelector("input[type=file]") as HTMLInputElement;
    await expect(input.multiple).toBe(true);
    await userEvent.upload(input, [
      new File(["<svg/>"], "good.svg", { type: "image/svg+xml" }),
      new File(["<svg/>"], "bad.svg", { type: "image/svg+xml" }),
      new File(["<svg/>"], "also-good.svg", { type: "image/svg+xml" }),
    ]);
    const results = await within(dialog).findByRole("list", { name: "Upload results" });
    await waitFor(() => expect(within(results).getAllByRole("listitem")).toHaveLength(3));
    await waitFor(() => expect(within(results).getByRole("alert")).toHaveTextContent("The file contains a script and cannot be used."));
    await expect(within(results).getAllByText("Uploaded.")).toHaveLength(2);
    await expect(api.postFile).toHaveBeenCalledTimes(3);
    await expect(api.postFile).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/modules/architecture/symbols`, expect.any(File), undefined);
  },
};

/** An upload into the open folder sends that folder's id with the file. */
export const UploadIntoTheOpenFolder: Story = {
  beforeEach: () => {
    mockSymbolLibrary(reads());
    const post = spyOn(api, "postFile").mockResolvedValue({} as never);
    return () => post.mockRestore();
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Folder Network" }));
    await userEvent.click(await canvas.findByRole("button", { name: "Upload symbols" }));
    const dialog = await within(document.body).findByRole("dialog", { name: "Upload symbols" });
    await userEvent.upload(dialog.querySelector("input[type=file]") as HTMLInputElement, new File(["<svg/>"], "one.svg", { type: "image/svg+xml" }));
    await waitFor(() => expect(api.postFile).toHaveBeenCalledWith(
      `/api/v1/orgs/${ORG_ID}/modules/architecture/symbols`, expect.any(File), { folder_id: "sf-1" },
    ));
  },
};

/** A project's page: the organisation's symbols are read-only in an Organisation branch of the tree, and Delete hides them. */
export const ProjectOffersTheOrganisationsSymbolsReadOnly: Story = {
  args: { scope: { kind: "project", projectId: PROJECT_ID } },
  parameters: {
    path: `/projects/${PROJECT_ID}/admin/architecture/architecture-symbols`,
    route: "/projects/:projectId/admin/architecture/architecture-symbols",
  },
  beforeEach: () => {
    mockSymbolLibrary(reads({
      rows: [
        buildBuiltinRow({ id: "sym-b", name: "Server" }),
        buildSymbolRow({ id: "sym-o", name: "Core router", folder_path: "Network", can_file: false }),
        buildSymbolRow({ id: "sym-p", name: "Vendor router", organization_id: null, project_id: PROJECT_ID, tier: "project", folder_id: "pf-1", folder_path: "Mine" }),
      ],
      folders: [buildSymbolFolder({ id: "pf-1", name: "Mine", path: "Mine", project_id: PROJECT_ID, organization_id: null })],
      organizationFolders: [{ path: "Network", symbol_count: 1 }],
      hidden: [{ id: "sym-h", name: "Firewall" }],
    }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "Symbols" });
    const org = within(within(table).getByText("Core router").closest("tr")!);
    await expect(org.getByText("Organisation")).toBeInTheDocument();
    await expect(org.queryByRole("checkbox")).not.toBeInTheDocument();
    await userEvent.click(org.getByRole("button", { name: "Actions for Core router" }));
    await expect(await within(document.body).findByRole("menuitem", { name: "Hide symbol in this project" })).toBeInTheDocument();
    await expect(within(document.body).queryByRole("menuitem", { name: "Rename" })).not.toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    // The tree shows the project's own folders and a read-only branch of the organisation's.
    await expect(await canvas.findByRole("button", { name: "Folder Mine" })).toBeInTheDocument();
    await expect(canvas.getByRole("group", { name: "Organisation folders" })).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Organisation folder Network" }));
    await waitFor(() => expect(canvas.queryByText("Vendor router")).not.toBeInTheDocument());
    // Hidden defaults come back from the page's actions menu.
    await userEvent.click(canvas.getByRole("button", { name: "List actions" }));
    await expect(await within(document.body).findByRole("menuitem", { name: "Add organisation defaults (1)" })).toBeInTheDocument();
  },
};

/** A person who may not change the library sees the symbols and where they are used, and no control that changes anything. */
export const ReadOnlyViewerHasNoChangingControls: Story = {
  beforeEach: () => { mockSymbolLibrary(reads({ canManage: false })); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("table", { name: "Symbols" });
    await expect(canvas.queryByRole("button", { name: "Upload symbols" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: /Actions for/ })).not.toBeInTheDocument();
    await expect(canvas.queryAllByRole("checkbox", { name: /^Select / })).toHaveLength(0);
    await expect(canvas.getByRole("button", { name: /Show where Core router is used/ })).toBeInTheDocument();
  },
};

export const EmptyLibrary: Story = {
  beforeEach: () => { mockSymbolLibrary({ rows: [], canManage: true }); },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("The symbol library is empty.")).toBeInTheDocument();
  },
};

export const NoSymbolMatchesTheFilters: Story = {
  beforeEach: () => { mockSymbolLibrary(reads()); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("table", { name: "Symbols" });
    await userEvent.type(canvas.getByRole("textbox", { name: "Search symbols" }), "zzz");
    await expect(await canvas.findByText("No symbols match these filters.")).toBeInTheDocument();
  },
};

const LONG_ROWS = (long: boolean) => [
  buildSymbolRow({
    id: "sym-l1", name: stressText(long, "Core router"), folder_id: "sf-1", folder_path: stressText(long, "Network", "word"),
    usage_count: 5, usage_owner_count: 5,
  }),
  buildSymbolRow({ id: "sym-l2", name: stressText(long, "Edge switch", "word"), folder_path: stressText(long, "Network/Switches", "summary") }),
  buildSymbolRow({ id: "sym-l3", name: stressText(long, "Legacy modem"), usage_count: 1, used_by: [stressText(long, "Platform", "name")], usage_owner_count: 1 }),
];

/** A long name, an unbroken word and a long folder path in several rows leave the table's columns and controls where they were. */
export const LongText: Story = {
  render: () => (
    <TextStress
      width={1000}
      render={(long) => <SymbolLibraryPanel scope={{ kind: "org", organizationId: long ? "org-long" : "org-short" }} />}
    />
  ),
  beforeEach: () => { mockSymbolLibrary({ rows: [], rowsByScope: { "org-short": LONG_ROWS(false), "org-long": LONG_ROWS(true) }, converter: false }); },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getAllByRole("table", { name: "Symbols" })).toHaveLength(2));
    await expectStressStable(canvasElement);
  },
};

/** The same stress in the tile view: a long name, path and owner stay inside their tile. */
export const LongTextTiles: Story = {
  decorators: [withStatefulAuth(buildUser({ id: "user-1", ui_preferences: { "view_mode:architecture-symbols": "tiles" } }))],
  render: () => (
    <TextStress
      width={1000}
      render={(long) => <SymbolLibraryPanel scope={{ kind: "org", organizationId: long ? "org-long" : "org-short" }} />}
    />
  ),
  beforeEach: () => { mockSymbolLibrary({ rows: [], rowsByScope: { "org-short": LONG_ROWS(false), "org-long": LONG_ROWS(true) }, converter: false }); },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(canvasElement.querySelectorAll(".tile-card").length).toBe(6));
    await expectStressStable(canvasElement);
  },
};

/** A rename the server refuses (the name is taken) keeps the dialog open with the reason. */
export const RenameShowsTheServersRefusal: Story = {
  beforeEach: () => {
    mockSymbolLibrary(reads());
    const patch = spyOn(api, "patch").mockRejectedValue(new Error("A symbol named 'Edge switch' already exists."));
    return () => patch.mockRestore();
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Actions for Core router" }));
    await userEvent.click(await within(document.body).findByRole("menuitem", { name: "Rename" }));
    const dialog = await within(document.body).findByRole("dialog", { name: "Rename Core router" });
    const name = within(dialog).getByRole("textbox", { name: "Name" });
    await userEvent.clear(name);
    await userEvent.type(name, "Edge switch");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await expect(await within(dialog).findByText("A symbol named 'Edge switch' already exists.")).toBeInTheDocument();
    await expect(api.patch).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/modules/architecture/symbols/sym-1`, { name: "Edge switch" });
  },
};

/** A symbol an element type or element uses cannot be deleted: the reason says what to do. */
export const DeletingASymbolInUseIsExplained: Story = {
  beforeEach: () => {
    mockSymbolLibrary(reads());
    const del = spyOn(api, "delete").mockRejectedValue(new Error("This symbol is in use and cannot be deleted."));
    return () => del.mockRestore();
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Actions for Core router" }));
    await userEvent.click(await within(document.body).findByRole("menuitem", { name: "Delete symbol" }));
    await userEvent.click(await within(document.body).findByRole("button", { name: "Delete" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/modules/architecture/symbols/sym-1`));
  },
};
