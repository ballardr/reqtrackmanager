import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, screen, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import { buildCategoriesVariable, buildForm, buildPackApi, buildSet } from "../testing/reportPackFixtures";
import { withToast } from "../testing/storybook-helpers";
import { ReportPackSetsPanel } from "./ReportPackSetsPanel";

/** The Saved sets tab: named choices for a pack's variables and, in a project, what that project overrides. */
const meta: Meta<typeof ReportPackSetsPanel> = {
  title: "Components/Reports/ReportPackSetsPanel",
  component: ReportPackSetsPanel,
  args: { packId: "pack-1" },
  decorators: [withToast()],
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.endsWith("/form")) return buildForm();
      throw new Error(`unmocked path: ${path}`);
    });
  },
};
export default meta;

type Story = StoryObj<typeof ReportPackSetsPanel>;

const inherited = buildSet({ id: "set-org", name: "Org default", editable: false, overridable: true, base: { categories: ["Security"] } });
const overridden = buildSet({
  id: "set-over", name: "Team Alpha", editable: false, overridable: true, base: { categories: ["Security"] },
  override: { categories: ["Billing"] }, effective: { categories: ["Billing"] }, overridden_by: "project-1",
});
const added = buildSet({ id: "set-added", name: "Our team", origin: "project", project_id: "project-1", base: { categories: ["Usability"] }, effective: { categories: ["Usability"] } });

export const ListsSetsWithTheirValues: Story = {
  args: { api: buildPackApi([], { kind: "organization", initialSets: [buildSet()] }) },
  play: async ({ canvasElement }) => {
    const card = within(await within(canvasElement).findByRole("region", { name: "Team Alpha" }));
    await expect(card.getByText("Saved with the pack")).toBeInTheDocument();
    await expect(card.getByRole("cell", { name: "Security" })).toBeInTheDocument();
    await expect(card.getByRole("cell", { name: "Categories" })).toBeInTheDocument();
  },
};

export const CreatingASetSavesItsValues: Story = {
  args: { api: buildPackApi([], { kind: "organization", initialSets: [] }) },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "New saved set" }));
    const dialog = within(await screen.findByRole("dialog", { name: "New saved set" }));
    await userEvent.type(dialog.getByRole("textbox", { name: "Name" }), "Team Beta");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.api!.createSet).toHaveBeenCalledWith("pack-1", { name: "Team Beta", values: {} }));
    await expect(await within(document.body).findByText("Saved set saved.")).toBeInTheDocument();
  },
};

export const AnInheritedSetIsOverriddenNotEdited: Story = {
  args: { api: buildPackApi([], { initialSets: [inherited] }) },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Actions for Org default" }));
    const items = (await screen.findAllByRole("menuitem")).map((item) => item.textContent?.trim());
    await expect(items).toEqual(["Override for this project"]);
    await userEvent.click(await screen.findByRole("menuitem", { name: "Override for this project" }));
    const dialog = within(await screen.findByRole("dialog", { name: "Override Org default for this project" }));
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.api!.putOverride).toHaveBeenCalledWith("pack-1", "set-org", {}));
  },
};

export const AnOverriddenSetShowsTheSharedValueBesideTheProjectsAndCanBeReset: Story = {
  args: { api: buildPackApi([], { initialSets: [overridden] }) },
  play: async ({ canvasElement, args }) => {
    const card = within(await within(canvasElement).findByRole("region", { name: "Team Alpha" }));
    await expect(card.getByText("Overridden here")).toBeInTheDocument();
    await expect(card.getByRole("columnheader", { name: "Shared value" })).toBeInTheDocument();
    await expect(card.getByRole("cell", { name: "Security" })).toBeInTheDocument();
    await expect(card.getByRole("cell", { name: "Billing" })).toBeInTheDocument();
    await userEvent.click(card.getByRole("button", { name: "Actions for Team Alpha" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Reset to the shared values" }));
    await waitFor(() => expect(args.api!.resetOverride).toHaveBeenCalledWith("pack-1", "set-over"));
    await expect(await within(document.body).findByText("Override removed.")).toBeInTheDocument();
  },
};

export const AProjectCanAddItsOwnSetAndEditOrDeleteIt: Story = {
  args: { api: buildPackApi([], { initialSets: [added] }) },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Actions for Our team" }));
    const items = (await screen.findAllByRole("menuitem")).map((item) => item.textContent?.trim());
    await expect(items).toEqual(["Edit", "Delete"]);
    await userEvent.click(await screen.findByRole("menuitem", { name: "Delete" }));
    await userEvent.click(within(await screen.findByRole("dialog", { name: "Delete Our team?" })).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(args.api!.removeSet).toHaveBeenCalledWith("pack-1", "set-added"));
  },
};

export const AStaleValueIsFlaggedNotHidden: Story = {
  args: {
    api: buildPackApi([], {
      kind: "organization",
      initialSets: [buildSet({ warnings: ['A value chosen for "Categories" is not one of its current options, so it may match nothing.'] })],
    }),
  },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByRole("status")).toHaveTextContent(/not one of its current options/);
  },
};

export const APackWithoutVariablesCannotHaveSets: Story = {
  args: { api: buildPackApi([], { kind: "organization", initialSets: [] }) },
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async () => buildForm({ variables: [], sets: [] }));
  },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByRole("button", { name: "New saved set" })).toBeDisabled();
    await expect(within(canvasElement).getByText("Add variables to the pack first.")).toBeInTheDocument();
  },
};

export const ALayoutOfTheFormUsesTheVariablesLabels: Story = {
  args: { api: buildPackApi([], { kind: "organization", initialSets: [buildSet({ base: { team: "Alpha" }, effective: { team: "Alpha" } })] }) },
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async () => buildForm({ variables: [buildCategoriesVariable({ name: "team", label: "Team", type: "text", multiple: false, options: null })] }));
  },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByRole("cell", { name: "Team" })).toBeInTheDocument();
  },
};
