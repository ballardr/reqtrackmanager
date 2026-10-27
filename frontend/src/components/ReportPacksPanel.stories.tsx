import type { Decorator, Meta, StoryObj } from "@storybook/react-vite";
import { expect, screen, userEvent, waitFor, within } from "storybook/test";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { buildPackApi, buildPackSummary } from "../testing/reportPackFixtures";
import { ReportPacksPanel } from "./ReportPacksPanel";

/** The panel at "/" with a stand-in for the editor, so a story can see that opening a pack navigates. */
const withEditorRoute: Decorator = (Story) => (
  <MemoryRouter initialEntries={["/"]}>
    <Routes>
      <Route path="/" element={<Story />} />
      <Route path="/projects/project-1/report-packs/:packId" element={<p>Editor opened</p>} />
      <Route path="/orgs/org-1/report-packs/:packId" element={<p>Organisation editor opened</p>} />
    </Routes>
  </MemoryRouter>
);

/** The Report packs list of Project Admin and Org Admin: own and shared packs, create, edit, copy, delete and, in a project, hide and restore. */
const meta: Meta<typeof ReportPacksPanel> = {
  title: "Components/Reports/ReportPacksPanel",
  component: ReportPacksPanel,
  decorators: [withEditorRoute],
};
export default meta;

type Story = StoryObj<typeof ReportPacksPanel>;

const shared = buildPackSummary({
  id: "pack-shared", name: "Organisation handover", description: "", origin: "organization", editable: false, project_id: null, entries: 1,
});

export const ListsOwnAndSharedPacks: Story = {
  args: { api: buildPackApi([buildPackSummary(), shared]) },
  play: async ({ canvasElement }) => {
    const table = await within(canvasElement).findByRole("table", { name: "Report packs" });
    await expect(within(table).getByRole("link", { name: /Handover pack/ })).toBeInTheDocument();
    await expect(within(table).getByText("3 reports")).toBeInTheDocument();
    await expect(within(table).getByText("1 report")).toBeInTheDocument();
    await expect(within(table).getByText("The organisation")).toBeInTheDocument();
  },
};

export const AnOrganisationListHasNoSharedFromColumn: Story = {
  args: { api: buildPackApi([buildPackSummary({ project_id: null, origin: "organization" })], { kind: "organization" }) },
  play: async ({ canvasElement }) => {
    const table = await within(canvasElement).findByRole("table", { name: "Report packs" });
    await expect(within(table).queryByRole("columnheader", { name: "Shared from" })).not.toBeInTheDocument();
  },
};

export const EmptyScopeSaysSo: Story = {
  args: { api: buildPackApi([]) },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("No report packs yet.")).toBeInTheDocument();
  },
};

export const AFailedLoadIsReported: Story = {
  args: { api: buildPackApi([], { list: async () => { throw new Error("denied"); } }) },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByRole("alert")).toHaveTextContent("The report packs could not be loaded.");
  },
};

export const CreatingAPackOpensTheEditor: Story = {
  args: { api: buildPackApi([]) },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "New pack" }));
    const dialog = within(await screen.findByRole("dialog", { name: "New report pack" }));
    await userEvent.type(dialog.getByRole("textbox", { name: "Name" }), "Board pack");
    await userEvent.click(dialog.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(args.api!.create).toHaveBeenCalledWith(expect.objectContaining({ name: "Board pack" })));
    await expect(await screen.findByText("Editor opened")).toBeInTheDocument();
  },
};

export const MakingACopyOfASharedPackCreatesItInThisScope: Story = {
  args: { api: buildPackApi([shared]) },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Actions for Organisation handover" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Make a copy" }));
    await waitFor(() => expect(args.api!.create).toHaveBeenCalledWith(expect.objectContaining({ name: "Organisation handover (copy)" })));
    await expect(await screen.findByText("Editor opened")).toBeInTheDocument();
  },
};

export const ASharedPackCannotBeDeletedOnlyHidden: Story = {
  args: { api: buildPackApi([shared]) },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Actions for Organisation handover" }));
    const items = (await screen.findAllByRole("menuitem")).map((item) => item.textContent?.trim());
    await expect(items).toEqual(["View pack", "Make a copy", "Hide in this project"]);
    await userEvent.click(await screen.findByRole("menuitem", { name: "Hide in this project" }));
    await userEvent.click(within(await screen.findByRole("dialog", { name: "Hide Organisation handover in this project?" })).getByRole("button", { name: "Hide" }));
    await waitFor(() => expect(args.api!.setHidden).toHaveBeenCalledWith("pack-shared", true));
  },
};

export const DeletingAnOwnPackNeedsTheNameTyped: Story = {
  args: { api: buildPackApi([buildPackSummary()]) },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Actions for Handover pack" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Delete" }));
    const dialog = within(await screen.findByRole("dialog", { name: "Delete Handover pack?" }));
    await expect(dialog.getByRole("button", { name: "Delete" })).toBeDisabled();
    await userEvent.type(dialog.getByRole("textbox"), "Handover pack");
    await userEvent.click(dialog.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(args.api!.remove).toHaveBeenCalledWith("pack-1"));
  },
};
