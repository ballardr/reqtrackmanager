import type { Decorator, Meta, StoryObj } from "@storybook/react-vite";
import { expect, screen, userEvent, waitFor, within } from "storybook/test";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { buildFolderApi } from "../testing/reportFolderFixtures";
import { buildLayoutApi, buildLayoutSummary } from "../testing/reportLayoutFixtures";
import { buildPackApi, buildPackSummary } from "../testing/reportPackFixtures";
import { buildPlacement, buildPlacementApi } from "../testing/reportPlacementFixtures";
import { requiredCaptions } from "../testing/requiredMarkers";
import { buildUser, withStatefulAuth, withToast } from "../testing/storybook-helpers";
import { ReportSetupPanel } from "./ReportSetupPanel";

/** The panel at "/" with stand-ins for the designer and the pack editor, so a story sees that opening a row navigates. */
const withRoutes: Decorator = (Story) => (
  <MemoryRouter initialEntries={["/"]}>
    <Routes>
      <Route path="/" element={<Story />} />
      <Route path="/projects/project-1/report-layouts/:layoutId" element={<p>Designer opened</p>} />
      <Route path="/projects/project-1/report-packs/:packId" element={<p>Pack editor opened</p>} />
    </Routes>
  </MemoryRouter>
);

const OWN_LAYOUT = buildLayoutSummary({ id: "1", name: "Handover document", description: "For the external team." });
const OWN_TABLE = buildLayoutSummary({ id: "2", name: "Handover rows", description: "", family: "table", folder: "Handover" });
const SHARED_LAYOUT = buildLayoutSummary({
  id: "3", name: "Organisation requirements", description: "", origin: "organization", editable: false, project_id: null,
});
const OWN_PACK = buildPackSummary({ id: "1", name: "Programme handover", description: "A zip of the handover reports.", entries: 3 });

const layoutPlacement = (id: string, title: string, kind: "report" | "sheet", folder: string) => buildPlacement({
  report_key: `layout:${id}`, title, description: "", kind, group: "Custom reports", default_folder: folder, folder, can_hide: false,
});

/** The placements the server would list for the layouts and pack above plus two module reports. */
const placements = () => [
  buildPlacement(),
  buildPlacement({ report_key: "report:decisions.d2", title: "Approval ageing", description: "" }),
  layoutPlacement("1", "Handover document", "report", "Custom reports"),
  layoutPlacement("2", "Handover rows", "sheet", "Handover"),
  layoutPlacement("3", "Organisation requirements", "report", "Custom reports"),
  buildPlacement({
    report_key: "pack:1", title: "Programme handover", description: "", kind: "pack", group: "Report packs", default_folder: "Report packs",
    folder: "Report packs", can_hide: false,
  }),
];

/**
 * Report setup of Project Admin and Org Admin: every report, pack and table a scope can arrange as one folder list,
 * with the actions that apply to each row, and folder actions on the folders.
 */
/** A fresh set of fakes per story, so a story that hides or moves something does not change the next one. */
const fresh = () => ({
  layoutApi: buildLayoutApi([OWN_LAYOUT, OWN_TABLE, SHARED_LAYOUT]),
  packApi: buildPackApi([OWN_PACK]),
  placementApi: buildPlacementApi(placements()),
  folderApi: buildFolderApi(),
});

const meta: Meta<typeof ReportSetupPanel> = {
  title: "Components/Reports/ReportSetupPanel",
  component: ReportSetupPanel,
  decorators: [withToast(), withStatefulAuth(buildUser({ ui_preferences: {} })), withRoutes],
  args: fresh(),
};
export default meta;

type Story = StoryObj<typeof ReportSetupPanel>;

const list = async (canvasElement: HTMLElement) => within(await within(canvasElement).findByRole("treegrid", { name: "Reports, packs and tables" }));
const expand = (grid: ReturnType<typeof within>, folder: string) => userEvent.click(grid.getByRole("button", { name: `Expand ${folder}` }));

export const ListsLayoutsPacksTablesAndModuleReportsInOneFolderList: Story = {
  args: fresh(),
  play: async ({ canvasElement }) => {
    const grid = await list(canvasElement);
    await expand(grid, "Custom reports");
    await expand(grid, "Decision Management");
    await expand(grid, "Handover");
    await expand(grid, "Report packs");
    await expect(grid.getByRole("button", { name: /^Handover document/ })).toBeInTheDocument();
    await expect(grid.getByRole("button", { name: /^Approval ageing/ })).toBeInTheDocument();
    await expect(grid.getByRole("button", { name: /^Programme handover/ })).toBeInTheDocument();
    // The type is the icon, named in words; there is no Kind column.
    await expect(grid.getAllByRole("img", { name: "Sheet" }).length).toBeGreaterThan(0);
    await expect(grid.getAllByRole("img", { name: "Pack" }).length).toBeGreaterThan(0);
    await expect(grid.queryByRole("columnheader", { name: "Kind" })).not.toBeInTheDocument();
    await expect(grid.getByRole("columnheader", { name: "Shared from" })).toBeInTheDocument();
  },
};

/** Version, Type and Folder are off until chosen (the icon shows the type, the nesting the folder); Name cannot be hidden. */
export const VersionTypeAndFolderColumnsAreOffUntilChosen: Story = {
  args: fresh(),
  play: async ({ canvasElement }) => {
    const grid = await list(canvasElement);
    for (const name of ["Version", "Type", "Folder"]) await expect(grid.queryByRole("columnheader", { name })).not.toBeInTheDocument();
    await expect(grid.getByRole("columnheader", { name: "Last changed" })).toBeInTheDocument();
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Choose columns" }));
    const chooser = within(await screen.findByRole("dialog", { name: "Columns" }));
    await expect(chooser.getByRole("checkbox", { name: "Name" })).toBeDisabled();
    await userEvent.click(chooser.getByRole("checkbox", { name: "Type" }));
    await userEvent.click(chooser.getByRole("checkbox", { name: "Folder" }));
    await userEvent.click(chooser.getByRole("checkbox", { name: "Version" }));
    await expect(grid.getByRole("columnheader", { name: /Type/ })).toBeInTheDocument();
    await expect(grid.getByRole("columnheader", { name: /Folder/ })).toBeInTheDocument();
    await expect(grid.getByRole("columnheader", { name: /Version/ })).toBeInTheDocument();
    await userEvent.click(chooser.getByRole("button", { name: "Show the default columns" }));
    await expect(grid.queryByRole("columnheader", { name: "Type" })).not.toBeInTheDocument();
  },
};

export const AnOrganisationListHasNoSharedFromColumnAndOffersStarterLayouts: Story = {
  args: {
    layoutApi: buildLayoutApi([OWN_LAYOUT], { kind: "organization" }),
    packApi: buildPackApi([], { kind: "organization" }),
    placementApi: buildPlacementApi([layoutPlacement("1", "Handover document", "report", "Custom reports")], "organization"),
    folderApi: buildFolderApi([], "organization"),
  },
  play: async ({ canvasElement, args }) => {
    const grid = await list(canvasElement);
    await expect(grid.queryByRole("columnheader", { name: "Shared from" })).not.toBeInTheDocument();
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Add starter layouts" }));
    await waitFor(() => expect(args.layoutApi!.addStarters).toHaveBeenCalledTimes(1));
    await expect(await within(document.body).findByText("Every starter layout is already here.")).toBeInTheDocument();
  },
};

export const TheNewMenuCreatesALayoutAPackOrAFolder: Story = {
  args: fresh(),
  play: async ({ canvasElement }) => {
    await list(canvasElement);
    await userEvent.click(within(canvasElement).getByRole("button", { name: "New" }));
    await expect(await screen.findByRole("menuitem", { name: "New layout" })).toBeInTheDocument();
    await expect(screen.getByRole("menuitem", { name: "New pack" })).toBeInTheDocument();
    await expect(screen.getByRole("menuitem", { name: "New folder" })).toBeInTheDocument();
  },
};

export const CreatingALayoutOpensTheDesigner: Story = {
  args: fresh(),
  play: async ({ canvasElement, args }) => {
    await list(canvasElement);
    await userEvent.click(within(canvasElement).getByRole("button", { name: "New" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "New layout" }));
    const dialog = within(await screen.findByRole("dialog", { name: "New report layout" }));
    await userEvent.type(dialog.getByRole("textbox", { name: "Name" }), "Risk rows");
    await userEvent.click(dialog.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(args.layoutApi!.create).toHaveBeenCalledWith(expect.objectContaining({ name: "Risk rows" })));
    await expect(await screen.findByText("Designer opened")).toBeInTheDocument();
  },
};

export const CreatingAPackOpensTheEditor: Story = {
  args: fresh(),
  play: async ({ canvasElement, args }) => {
    await list(canvasElement);
    await userEvent.click(within(canvasElement).getByRole("button", { name: "New" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "New pack" }));
    const dialog = within(await screen.findByRole("dialog", { name: "New report pack" }));
    await userEvent.type(dialog.getByRole("textbox", { name: "Name" }), "Audit pack");
    await userEvent.click(dialog.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(args.packApi!.create).toHaveBeenCalledWith(expect.objectContaining({ name: "Audit pack" })));
    await expect(await screen.findByText("Pack editor opened")).toBeInTheDocument();
  },
};

export const NewFolderFromTheMenuAddsAnEmptyFolder: Story = {
  args: fresh(),
  play: async ({ canvasElement, args }) => {
    await list(canvasElement);
    await userEvent.click(within(canvasElement).getByRole("button", { name: "New" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "New folder" }));
    const dialog = within(await screen.findByRole("dialog", { name: "New folder" }));
    await expect(requiredCaptions(document.body)).toEqual(["Name of the new folder"]);
    await userEvent.type(dialog.getByRole("textbox", { name: /Name of the new folder/ }), "Audit");
    await userEvent.click(dialog.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(args.folderApi!.add).toHaveBeenCalledWith("Audit"));
    const grid = await list(canvasElement);
    await expand(grid, "Audit");
    await expect(await grid.findByText("Empty folder")).toBeInTheDocument();
  },
};

export const AFolderTheScopeOwnsCanBeRenamedAndDeleted: Story = {
  args: fresh(),
  play: async ({ canvasElement, args }) => {
    const grid = await list(canvasElement);
    await userEvent.click(grid.getByRole("button", { name: "Actions for the folder Handover" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Rename" }));
    const dialog = within(await screen.findByRole("dialog", { name: "Rename" }));
    const name = dialog.getByRole("textbox", { name: /New name for Handover/ });
    await userEvent.clear(name);
    await userEvent.type(name, "Handed over");
    await userEvent.click(dialog.getByRole("button", { name: "Save name" }));
    await waitFor(() => expect(args.folderApi!.rename).toHaveBeenCalledWith("Handover", "Handed over"));
    await userEvent.click(await grid.findByRole("button", { name: "Actions for the folder Handed over" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Delete" }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(args.folderApi!.remove).toHaveBeenCalledWith("Handed over"));
  },
};

export const AFolderThatBelongsToATierAboveOffersOnlyNewInside: Story = {
  args: fresh(),
  play: async ({ canvasElement }) => {
    const grid = await list(canvasElement);
    await userEvent.click(grid.getByRole("button", { name: "Actions for the folder Shared" }));
    await expect(await screen.findByRole("menuitem", { name: "New folder inside" })).toBeInTheDocument();
    await expect(screen.queryByRole("menuitem", { name: "Rename" })).not.toBeInTheDocument();
    await expect(screen.queryByRole("menuitem", { name: "Delete" })).not.toBeInTheDocument();
  },
};

export const AnOwnLayoutOffersTheOwnerActions: Story = {
  args: fresh(),
  play: async ({ canvasElement }) => {
    const grid = await list(canvasElement);
    await expand(grid, "Custom reports");
    await userEvent.click(grid.getByRole("button", { name: "Actions for Handover document" }));
    for (const name of ["Open designer", "Edit details", "Move to folder…", "Make a copy", "Delete"]) {
      await expect(await screen.findByRole("menuitem", { name })).toBeInTheDocument();
    }
    await expect(screen.queryByRole("menuitem", { name: "Hide in this project" })).not.toBeInTheDocument();
  },
};

export const ASharedLayoutCanBeViewedCopiedMovedOrHiddenButNotEditedOrDeleted: Story = {
  args: fresh(),
  play: async ({ canvasElement }) => {
    const grid = await list(canvasElement);
    await expand(grid, "Custom reports");
    await userEvent.click(grid.getByRole("button", { name: "Actions for Organisation requirements" }));
    for (const name of ["View layout", "Move to folder…", "Make a copy", "Hide in this project"]) {
      await expect(await screen.findByRole("menuitem", { name })).toBeInTheDocument();
    }
    await expect(screen.queryByRole("menuitem", { name: "Edit details" })).not.toBeInTheDocument();
    await expect(screen.queryByRole("menuitem", { name: "Delete" })).not.toBeInTheDocument();
  },
};

export const OpeningALayoutGoesToTheDesigner: Story = {
  args: fresh(),
  play: async ({ canvasElement }) => {
    const grid = await list(canvasElement);
    await expand(grid, "Custom reports");
    await userEvent.click(grid.getByRole("button", { name: /^Handover document/ }));
    await expect(await screen.findByText("Designer opened")).toBeInTheDocument();
  },
};

export const OpeningAPackGoesToTheEditor: Story = {
  args: fresh(),
  play: async ({ canvasElement }) => {
    const grid = await list(canvasElement);
    await expand(grid, "Report packs");
    await userEvent.click(grid.getByRole("button", { name: /^Programme handover/ }));
    await expect(await screen.findByText("Pack editor opened")).toBeInTheDocument();
  },
};

export const MovingAModuleReportSetsAPlacement: Story = {
  args: fresh(),
  play: async ({ canvasElement, args }) => {
    const grid = await list(canvasElement);
    await expand(grid, "Decision Management");
    await userEvent.click(grid.getByRole("button", { name: "Actions for Decision register" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Move to folder…" }));
    const dialog = within(await screen.findByRole("dialog", { name: "Move Decision register" }));
    await userEvent.click(await dialog.findByRole("radio", { name: "Handover" }));
    await userEvent.click(dialog.getByRole("button", { name: "Move" }));
    await waitFor(() => expect(args.placementApi!.set).toHaveBeenCalledWith({ report_key: "report:decisions.d1", folder: "Handover" }));
    await expect(await within(document.body).findByText("Report moved.")).toBeInTheDocument();
  },
};

export const MovingAnOwnLayoutEditsItsFolder: Story = {
  args: fresh(),
  play: async ({ canvasElement, args }) => {
    const grid = await list(canvasElement);
    await expand(grid, "Custom reports");
    await userEvent.click(grid.getByRole("button", { name: "Actions for Handover document" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Move to folder…" }));
    const dialog = within(await screen.findByRole("dialog", { name: "Move Handover document" }));
    await userEvent.click(await dialog.findByRole("radio", { name: "Handover" }));
    await userEvent.click(dialog.getByRole("button", { name: "Move" }));
    await waitFor(() => expect(args.layoutApi!.update).toHaveBeenCalledWith("1", { folder: "Handover" }));
    await expect(args.placementApi!.set).not.toHaveBeenCalled();
  },
};

export const HidingAModuleReportConfirmsAndCanBeShownAgain: Story = {
  args: fresh(),
  play: async ({ canvasElement, args }) => {
    const grid = await list(canvasElement);
    await expand(grid, "Decision Management");
    await userEvent.click(grid.getByRole("button", { name: "Actions for Approval ageing" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Hide from the list" }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Hide from the list" }));
    await waitFor(() => expect(args.placementApi!.set).toHaveBeenCalledWith({ report_key: "report:decisions.d2", hidden: true }));
    await expect(await grid.findByText("Hidden")).toBeInTheDocument();
    await userEvent.click(grid.getByRole("button", { name: "Actions for Approval ageing" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Show in the list" }));
    await waitFor(() => expect(grid.queryByText("Hidden")).not.toBeInTheDocument());
  },
};

export const HidingASharedLayoutInAProjectAndRestoringIt: Story = {
  args: fresh(),
  play: async ({ canvasElement, args }) => {
    const grid = await list(canvasElement);
    await expand(grid, "Custom reports");
    await userEvent.click(grid.getByRole("button", { name: "Actions for Organisation requirements" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Hide in this project" }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Hide" }));
    await waitFor(() => expect(args.layoutApi!.setHidden).toHaveBeenCalledWith("3", true));
    await userEvent.click(await within(canvasElement).findByRole("button", { name: /Add organisation defaults/ }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: /Add|Restore|Show/ }));
    await waitFor(() => expect(args.layoutApi!.restore).toHaveBeenCalledWith(["3"]));
  },
};

export const DeletingAnOwnPackNeedsItsNameTyped: Story = {
  args: fresh(),
  play: async ({ canvasElement, args }) => {
    const grid = await list(canvasElement);
    await expand(grid, "Report packs");
    await userEvent.click(grid.getByRole("button", { name: "Actions for Programme handover" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Delete" }));
    const dialog = within(await screen.findByRole("dialog"));
    await expect(dialog.getByRole("button", { name: "Delete" })).toBeDisabled();
    await userEvent.type(dialog.getByRole("textbox"), "Programme handover");
    await userEvent.click(dialog.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(args.packApi!.remove).toHaveBeenCalledWith("1"));
  },
};

export const SearchOpensEveryFolderThatHoldsAMatch: Story = {
  args: fresh(),
  play: async ({ canvasElement }) => {
    const grid = await list(canvasElement);
    await expect(grid.queryByRole("button", { name: /^Approval ageing/ })).not.toBeInTheDocument();
    await userEvent.type(within(canvasElement).getByRole("textbox", { name: "Search reports" }), "ageing");
    await expect(await grid.findByRole("button", { name: /^Approval ageing/ })).toBeInTheDocument();
    await expect(grid.queryByRole("button", { name: /^Handover document/ })).not.toBeInTheDocument();
  },
};

export const TheTypeFilterShowsOnlyPacks: Story = {
  args: fresh(),
  play: async ({ canvasElement }) => {
    const grid = await list(canvasElement);
    await userEvent.selectOptions(within(canvasElement).getByRole("combobox", { name: "Type" }), "pack");
    await expect(await grid.findByRole("button", { name: /^Programme handover/ })).toBeInTheDocument();
    await expect(grid.queryByRole("button", { name: /^Handover document/ })).not.toBeInTheDocument();
  },
};

export const ALoadFailureIsReportedNotHidden: Story = {
  args: { ...fresh(), placementApi: { ...buildPlacementApi(placements()), list: async () => { throw new Error("denied"); } } },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByRole("alert")).toHaveTextContent("The report setup could not be loaded.");
  },
};
