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
    await waitFor(() => expect(args.api!.update).toHaveBeenCalledWith("layout-1", { name: "Renamed", description: "Every requirement with its component." }));
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
