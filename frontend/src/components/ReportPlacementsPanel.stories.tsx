import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, screen, userEvent, waitFor, within } from "storybook/test";

import { buildFolderApi } from "../testing/reportFolderFixtures";
import { buildPlacement, buildPlacementApi, buildPlacements } from "../testing/reportPlacementFixtures";
import { withToast } from "../testing/storybook-helpers";
import { ReportPlacementsPanel } from "./ReportPlacementsPanel";

/**
 * Arranges the Reports list for a project or organisation: where each report is filed and which module reports are
 * shown, with the default and the tier that set an override visible beside each.
 */
const meta: Meta<typeof ReportPlacementsPanel> = {
  title: "Components/Reports/ReportPlacementsPanel",
  component: ReportPlacementsPanel,
  decorators: [withToast()],
  args: { api: buildPlacementApi(), folderApi: buildFolderApi() },
};
export default meta;

type Story = StoryObj<typeof ReportPlacementsPanel>;

const table = async (canvasElement: HTMLElement) => within(await within(canvasElement).findByRole("table", { name: "Reports and where they are filed" }));

export const ListsEveryReportWithItsFolderAndKind: Story = {
  play: async ({ canvasElement }) => {
    const rows = await table(canvasElement);
    await expect(rows.getByText("Decision register")).toBeInTheDocument();
    await expect(rows.getByText("Handover rows")).toBeInTheDocument();
    await expect(rows.getByText("Sheet")).toBeInTheDocument();
    await expect(rows.getByText("Pack")).toBeInTheDocument();
    await expect(rows.getAllByText("Decision Management").length).toBeGreaterThan(1); // the module under the title and the folder
  },
};

export const MovingAReportToANestedFolderShowsTheDefaultBesideIt: Story = {
  play: async ({ canvasElement, args }) => {
    const rows = await table(canvasElement);
    await userEvent.click(rows.getByRole("button", { name: "Actions for Decision register" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Move to folder…" }));
    const dialog = within(await screen.findByRole("dialog", { name: "Move Decision register" }));
    await expect(await dialog.findByRole("radio", { name: "Decision Management" })).toBeChecked(); // its default folder is offered
    await userEvent.click(dialog.getByRole("button", { name: "New folder inside" }));
    await userEvent.type(dialog.getByRole("textbox", { name: "Name of the new folder inside Decision Management" }), "Governance");
    await userEvent.click(dialog.getByRole("button", { name: "Add" }));
    await expect(await dialog.findByRole("radio", { name: "Governance" })).toBeChecked();
    await userEvent.click(dialog.getByRole("button", { name: "Move" }));
    await waitFor(() => expect(args.api!.set).toHaveBeenCalledWith({ report_key: "report:decisions.d1", folder: "Decision Management/Governance" }));
    await expect(await rows.findByText("Decision Management/Governance")).toBeInTheDocument();
    await expect(rows.getByText("Default: Decision Management")).toBeInTheDocument();
    await expect(await within(document.body).findByText("Report moved.")).toBeInTheDocument();
  },
};

/** The top level is a choice of its own: it files the report outside every folder. */
export const AReportCanBeFiledAtTheTopLevel: Story = {
  play: async ({ canvasElement, args }) => {
    const rows = await table(canvasElement);
    await userEvent.click(rows.getByRole("button", { name: "Actions for Decision register" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Move to folder…" }));
    const dialog = within(await screen.findByRole("dialog", { name: "Move Decision register" }));
    await userEvent.click(await dialog.findByRole("radio", { name: "Top level" }));
    await userEvent.click(dialog.getByRole("button", { name: "Move" }));
    await waitFor(() => expect(args.api!.set).toHaveBeenCalledWith({ report_key: "report:decisions.d1", folder: "" }));
  },
};

export const ResettingAFolderGoesBackToTheDefault: Story = {
  args: { api: buildPlacementApi([buildPlacement({ folder: "Governance", folder_from: "project", own_folder: "Governance" })]) },
  play: async ({ canvasElement, args }) => {
    const rows = await table(canvasElement);
    await userEvent.click(rows.getByRole("button", { name: "Actions for Decision register" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Reset folder to default" }));
    await waitFor(() => expect(args.api!.set).toHaveBeenCalledWith({ report_key: "report:decisions.d1", folder: null }));
    await waitFor(() => expect(rows.queryByText(/Default:/)).not.toBeInTheDocument());
    await expect(rows.getAllByText("Decision Management").length).toBe(2);
    await expect(rows.queryByText(/Default:/)).not.toBeInTheDocument();
  },
};

/** Hiding asks first, says what it does not do, and a hidden report stays listed so it can be shown again. */
export const HidingAModuleReportConfirmsAndCanBeUndone: Story = {
  play: async ({ canvasElement, args }) => {
    const rows = await table(canvasElement);
    await userEvent.click(rows.getByRole("button", { name: "Actions for Approval ageing" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Hide from the list" }));
    const confirm = within(await screen.findByRole("dialog"));
    await expect(confirm.getByText(/anyone with access can still run it/)).toBeInTheDocument();
    await userEvent.click(confirm.getByRole("button", { name: "Hide from the list" }));
    await waitFor(() => expect(args.api!.set).toHaveBeenCalledWith({ report_key: "report:decisions.d2", hidden: true }));
    await expect(await rows.findByText("Hidden")).toBeInTheDocument();
    await userEvent.click(rows.getByRole("button", { name: "Actions for Approval ageing" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Show in the list" }));
    await waitFor(() => expect(rows.queryByText("Hidden")).not.toBeInTheDocument());
  },
};

/** A layout or a pack is hidden from its own list, so only moving is offered here. */
export const ALayoutOrPackCanOnlyBeMoved: Story = {
  play: async ({ canvasElement }) => {
    const rows = await table(canvasElement);
    await userEvent.click(rows.getByRole("button", { name: "Actions for Handover document" }));
    await expect(await screen.findByRole("menuitem", { name: "Move to folder…" })).toBeInTheDocument();
    await expect(screen.queryByRole("menuitem", { name: "Hide from the list" })).not.toBeInTheDocument();
  },
};

/** An override set by the organisation reads as such in a project, and the project can show what the organisation hid. */
export const AProjectSeesWhichTierSetAnOverride: Story = {
  args: {
    api: buildPlacementApi([
      buildPlacement({ folder: "Governance", folder_from: "organization", hidden: true, hidden_from: "organization" }),
    ]),
  },
  play: async ({ canvasElement, args }) => {
    const rows = await table(canvasElement);
    await expect(rows.getByText(/Default: Decision Management · the organisation/)).toBeInTheDocument();
    await expect(rows.getByText("Hidden (the organisation)")).toBeInTheDocument();
    await userEvent.click(rows.getByRole("button", { name: "Actions for Decision register" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Show in the list" }));
    await waitFor(() => expect(args.api!.set).toHaveBeenCalledWith({ report_key: "report:decisions.d1", hidden: false }));
  },
};

/** A project that showed what the organisation hid can go back to following the organisation. */
export const AProjectCanReturnToFollowingTheOrganisation: Story = {
  args: {
    api: buildPlacementApi([
      buildPlacement({ hidden: false, hidden_from: "project", own_hidden: false }),
    ]),
  },
  play: async ({ canvasElement, args }) => {
    const rows = await table(canvasElement);
    await userEvent.click(rows.getByRole("button", { name: "Actions for Decision register" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Follow the default again" }));
    await waitFor(() => expect(args.api!.set).toHaveBeenCalledWith({ report_key: "report:decisions.d1", hidden: null }));
  },
};

export const SearchAndFiltersNarrowTheList: Story = {
  play: async ({ canvasElement }) => {
    const rows = await table(canvasElement);
    await userEvent.type(within(canvasElement).getByRole("textbox", { name: "Search reports" }), "risk");
    await expect(rows.getByText("Risk register")).toBeInTheDocument();
    await expect(rows.queryByText("Decision register")).not.toBeInTheDocument();
    await userEvent.clear(within(canvasElement).getByRole("textbox", { name: "Search reports" }));
    await userEvent.selectOptions(within(canvasElement).getByLabelText("Module"), "Report packs");
    await expect(rows.getByText("Programme handover")).toBeInTheDocument();
    await expect(rows.queryByText("Risk register")).not.toBeInTheDocument();
  },
};

export const ManyReportsArePagedWithShowMore: Story = {
  args: {
    api: buildPlacementApi([
      ...buildPlacements(),
      ...Array.from({ length: 40 }, (_, i) => buildPlacement({ report_key: `report:decisions.x${i}`, title: `Extra report ${i + 1}` })),
    ]),
  },
  play: async ({ canvasElement }) => {
    const rows = await table(canvasElement);
    await expect(rows.queryByText("Extra report 40")).not.toBeInTheDocument();
    await userEvent.click(await within(canvasElement).findByRole("button", { name: /Load more/ }));
    await expect(await rows.findByText("Extra report 40")).toBeInTheDocument();
    await expect(within(canvasElement).queryByRole("button", { name: /Load more/ })).not.toBeInTheDocument();
  },
};

export const AFailedLoadIsReported: Story = {
  args: { api: { ...buildPlacementApi(), list: async () => { throw new Error("denied"); } } },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByRole("alert")).toHaveTextContent("The report folders could not be loaded.");
  },
};

export const LightTheme: Story = { ...ListsEveryReportWithItsFolderAndKind, globals: { theme: "light" } };
export const DarkTheme: Story = { ...ListsEveryReportWithItsFolderAndKind, globals: { theme: "dark" } };
