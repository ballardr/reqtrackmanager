import type { Decorator, Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, screen, userEvent, waitFor, within } from "storybook/test";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { buildLayoutApi, buildLayoutSummary } from "../testing/reportLayoutFixtures";
import { requiredCaptions } from "../testing/requiredMarkers";
import { ReportLayoutsPanel } from "./ReportLayoutsPanel";

/** The panel at "/" with a stand-in for the designer, so a story can see that opening a layout navigates. */
const withDesignerRoute: Decorator = (Story) => (
  <MemoryRouter initialEntries={["/"]}>
    <Routes>
      <Route path="/" element={<Story />} />
      <Route path="/projects/project-1/report-layouts/:layoutId" element={<p>Designer opened</p>} />
      <Route path="/orgs/org-1/report-layouts/:layoutId" element={<p>Organisation designer opened</p>} />
    </Routes>
  </MemoryRouter>
);

/**
 * The Report layouts list of Project Admin and Org Admin: own and shared layouts, create, edit, copy, delete
 * and, in a project, hide and restore a shared one.
 */
const meta: Meta<typeof ReportLayoutsPanel> = {
  title: "Components/ReportLayoutsPanel",
  component: ReportLayoutsPanel,
  decorators: [withDesignerRoute],
};
export default meta;

type Story = StoryObj<typeof ReportLayoutsPanel>;

const body = () => within(document.body);

const shared = buildLayoutSummary({
  id: "layout-shared", name: "Organisation requirements pack", description: "", origin: "organization", editable: false, project_id: null,
});

export const ListsOwnAndSharedLayouts: Story = {
  args: { api: buildLayoutApi([buildLayoutSummary(), shared]) },
  play: async ({ canvasElement }) => {
    const table = await within(canvasElement).findByRole("table", { name: "Report layouts" });
    await expect(within(table).getByRole("link", { name: /Requirements by component/ })).toBeInTheDocument();
    await expect(within(table).getByText("Every requirement with its component.")).toBeInTheDocument();
    await expect(within(table).getByText("The organisation")).toBeInTheDocument();
    await expect(within(table).getByRole("columnheader", { name: "Shared from" })).toBeInTheDocument();
  },
};

export const AnOrganisationListHasNoSharedFromColumn: Story = {
  args: { api: buildLayoutApi([buildLayoutSummary({ project_id: null, origin: "organization" })], { kind: "organization" }) },
  play: async ({ canvasElement }) => {
    const table = await within(canvasElement).findByRole("table", { name: "Report layouts" });
    await expect(within(table).queryByRole("columnheader", { name: "Shared from" })).not.toBeInTheDocument();
    await expect(within(canvasElement).queryByRole("button", { name: /Add organisation defaults/ })).not.toBeInTheDocument();
  },
};

export const AddingTheStarterLayoutsToAnOrganisationSaysWhichWereAdded: Story = {
  args: {
    api: buildLayoutApi([], { kind: "organization", addStarters: fn(async () => ["Business Requirements Document", "Review Package"]) }),
  },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Add starter layouts" }));
    await waitFor(() => expect(args.api!.addStarters).toHaveBeenCalledTimes(1));
    await expect(await body().findByText("Added Business Requirements Document, Review Package.")).toBeInTheDocument();
  },
};

export const AddingStartersWhenAllArePresentSaysSo: Story = {
  args: { api: buildLayoutApi([buildLayoutSummary({ project_id: null, origin: "organization" })], { kind: "organization" }) },
  play: async ({ canvasElement }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Add starter layouts" }));
    await expect(await body().findByText("Every starter layout is already here.")).toBeInTheDocument();
  },
};

export const AProjectHasNoAddStartersButton: Story = {
  args: { api: buildLayoutApi([buildLayoutSummary()]) },
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByRole("table", { name: "Report layouts" });
    await expect(within(canvasElement).queryByRole("button", { name: "Add starter layouts" })).not.toBeInTheDocument();
  },
};

export const EmptyScopeSaysSo: Story = {
  args: { api: buildLayoutApi([]) },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("No report layouts yet.")).toBeInTheDocument();
  },
};

export const AFailedLoadIsReported: Story = {
  args: { api: buildLayoutApi([], { list: async () => { throw new Error("denied"); } }) },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByRole("alert")).toHaveTextContent("The report layouts could not be loaded.");
  },
};

export const CreatingALayoutOpensTheDesigner: Story = {
  args: { api: buildLayoutApi([]) },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "New layout" }));
    const dialog = within(await screen.findByRole("dialog", { name: "New report layout" }));
    await expect(requiredCaptions(document.body)).toEqual(["Name", "Kind of report"]);
    await expect(dialog.getByRole("button", { name: "Create" })).toBeDisabled();
    await userEvent.type(dialog.getByRole("textbox", { name: "Name" }), "Risk pack");
    await userEvent.selectOptions(dialog.getByRole("combobox", { name: "Kind of report" }), "table");
    await userEvent.click(dialog.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(args.api!.create).toHaveBeenCalledWith(expect.objectContaining({ name: "Risk pack", family: "table" })));
    await expect(await screen.findByText("Designer opened")).toBeInTheDocument();
    await expect(await body().findByText("Layout created.")).toBeInTheDocument();
  },
};

export const ATakenNameIsShownInTheDialog: Story = {
  args: {
    api: buildLayoutApi([], {
      create: async () => { throw new Error("A layout with this name already exists here."); },
    }),
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "New layout" }));
    const dialog = within(await screen.findByRole("dialog", { name: "New report layout" }));
    await userEvent.type(dialog.getByRole("textbox", { name: "Name" }), "Taken");
    await userEvent.click(dialog.getByRole("button", { name: "Create" }));
    await expect(await dialog.findByText("A layout with this name already exists here.")).toBeInTheDocument();
  },
};

export const EditingTheDetailsRenamesIt: Story = {
  args: { api: buildLayoutApi([buildLayoutSummary()]) },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Actions for Requirements by component" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Edit details" }));
    const dialog = within(await screen.findByRole("dialog", { name: "Layout details" }));
    await expect(dialog.queryByRole("combobox", { name: "Kind of report" })).not.toBeInTheDocument();
    const name = dialog.getByRole("textbox", { name: "Name" });
    await userEvent.clear(name);
    await userEvent.type(name, "Renamed");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.api!.update).toHaveBeenCalledWith("layout-1", { name: "Renamed", description: "Every requirement with its component.", folder: "" }));
    await expect(await body().findByText("Layout details saved.")).toBeInTheDocument();
  },
};

export const MakingACopyOfASharedLayoutCreatesItInThisScope: Story = {
  args: { api: buildLayoutApi([shared]) },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Actions for Organisation requirements pack" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Make a copy" }));
    await waitFor(() => expect(args.api!.create).toHaveBeenCalledWith(
      expect.objectContaining({ name: "Organisation requirements pack (copy)", family: "document" }),
    ));
    await expect(await screen.findByText("Designer opened")).toBeInTheDocument();
  },
};

export const ASharedLayoutCannotBeDeletedOnlyHidden: Story = {
  args: { api: buildLayoutApi([shared]) },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Actions for Organisation requirements pack" }));
    const items = (await screen.findAllByRole("menuitem")).map((item) => item.textContent?.trim());
    await expect(items).toEqual(["View layout", "Make a copy", "Hide in this project"]);
    await userEvent.click(await screen.findByRole("menuitem", { name: "Hide in this project" }));
    await userEvent.click(within(await screen.findByRole("dialog", { name: "Hide Organisation requirements pack in this project?" })).getByRole("button", { name: "Hide" }));
    await waitFor(() => expect(args.api!.setHidden).toHaveBeenCalledWith("layout-shared", true));
    await expect(await body().findByText("Layout hidden in this project.")).toBeInTheDocument();
    await waitFor(() => expect(within(canvasElement).queryByRole("link", { name: /Organisation requirements pack/ })).not.toBeInTheDocument());
    // It can be brought back.
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Add organisation defaults (1)" }));
    await userEvent.click(within(await screen.findByRole("dialog", { name: "Add organisation defaults" })).getByRole("button", { name: "Add 1 default" }));
    await waitFor(() => expect(args.api!.restore).toHaveBeenCalledWith(["layout-shared"]));
    await expect(await within(canvasElement).findByRole("link", { name: /Organisation requirements pack/ })).toBeInTheDocument();
  },
};

export const DeletingNeedsTheNameTyped: Story = {
  args: { api: buildLayoutApi([buildLayoutSummary()]) },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Actions for Requirements by component" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Delete" }));
    const dialog = within(await screen.findByRole("dialog", { name: "Delete Requirements by component?" }));
    await expect(dialog.getByRole("button", { name: "Delete" })).toBeDisabled();
    await userEvent.type(dialog.getByRole("textbox"), "Requirements by component");
    await userEvent.click(dialog.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(args.api!.remove).toHaveBeenCalledWith("layout-1"));
    await expect(await body().findByText("Layout deleted.")).toBeInTheDocument();
    await expect(await within(canvasElement).findByText("No report layouts yet.")).toBeInTheDocument();
  },
};

const many = [
  buildLayoutSummary({ id: "a", name: "Alpha requirements", folder: "Handover/Quarterly" }),
  buildLayoutSummary({ id: "b", name: "Beta rows", family: "table", folder: "Handover" }),
  buildLayoutSummary({ id: "c", name: "Gamma review", description: "Weekly review", folder: "" }),
  shared,
];

/** Each layout shows its folder, or "None". */
export const TheFolderColumnShowsEachLayoutsFolder: Story = {
  args: { api: buildLayoutApi(many) },
  play: async ({ canvasElement }) => {
    const table = within(await within(canvasElement).findByRole("table", { name: "Report layouts" }));
    await expect(table.getByRole("columnheader", { name: "Folder" })).toBeInTheDocument();
    await expect(table.getByText("Handover/Quarterly")).toBeInTheDocument();
    await expect(table.getAllByText("None").length).toBeGreaterThan(0);
  },
};

/** Search matches the name, description or folder; the kind, folder and shared-from filters narrow further. */
export const SearchAndFiltersNarrowTheList: Story = {
  args: { api: buildLayoutApi(many) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = within(await canvas.findByRole("table", { name: "Report layouts" }));
    await userEvent.type(canvas.getByRole("textbox", { name: "Search this list" }), "weekly");
    await expect(table.getByText("Gamma review")).toBeInTheDocument();
    await expect(table.queryByText("Alpha requirements")).not.toBeInTheDocument();
    await userEvent.clear(canvas.getByRole("textbox", { name: "Search this list" }));
    await userEvent.selectOptions(canvas.getByLabelText("Kind"), "Table");
    await expect(table.getByText("Beta rows")).toBeInTheDocument();
    await expect(table.queryByText("Alpha requirements")).not.toBeInTheDocument();
    await userEvent.selectOptions(canvas.getByLabelText("Kind"), "Any");
    await userEvent.selectOptions(canvas.getByLabelText("Folder"), "Handover");
    await expect(table.getByText("Alpha requirements")).toBeInTheDocument(); // a folder filter keeps what is inside it
    await expect(table.getByText("Beta rows")).toBeInTheDocument();
    await expect(table.queryByText("Gamma review")).not.toBeInTheDocument();
    await userEvent.selectOptions(canvas.getByLabelText("Folder"), "Any");
    await userEvent.selectOptions(canvas.getByLabelText("Shared from"), "Shared from elsewhere");
    await expect(table.getByText("Organisation requirements pack")).toBeInTheDocument();
    await expect(table.queryByText("Gamma review")).not.toBeInTheDocument();
  },
};

export const NothingMatchingSaysSoRatherThanThatThereAreNoLayouts: Story = {
  args: { api: buildLayoutApi(many) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("table", { name: "Report layouts" });
    await userEvent.type(canvas.getByRole("textbox", { name: "Search this list" }), "zzzz");
    await expect(await canvas.findByText("Nothing matches these filters.")).toBeInTheDocument();
  },
};

/** A long list shows its first page and loads the next on request. */
export const ALongListIsPaged: Story = {
  args: { api: buildLayoutApi(Array.from({ length: 30 }, (_, i) => buildLayoutSummary({ id: `l${i}`, name: `Layout ${String(i + 1).padStart(2, "0")}` }))) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("table", { name: "Report layouts" });
    await expect(canvas.queryByText("Layout 30")).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: /Load more/ }));
    await expect(await canvas.findByText("Layout 30")).toBeInTheDocument();
  },
};
