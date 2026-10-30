import type { Decorator, Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, screen, userEvent, waitFor, within } from "storybook/test";
import { MemoryRouter } from "react-router-dom";

import { buildDuplicateApi } from "../testing/reportDuplicateFixtures";
import { requiredCaptions } from "../testing/requiredMarkers";
import { buildUser, withStatefulAuth, withToast } from "../testing/storybook-helpers";
import { ReportDuplicateDialog } from "./ReportDuplicateDialog";

const withRouter: Decorator = (Story) => <MemoryRouter><Story /></MemoryRouter>;

/**
 * Duplicates one report layout or pack, or starts a layout from a built-in starter, as an editable basis for a new one:
 * the server plans the name, shadowing and pictures as the form changes, then creates the copy.
 */
const meta: Meta<typeof ReportDuplicateDialog> = {
  title: "Components/Reports/ReportDuplicateDialog",
  component: ReportDuplicateDialog,
  decorators: [withToast(), withStatefulAuth(buildUser({ ui_preferences: {} })), withRouter],
  args: {
    api: buildDuplicateApi(), source: { kind: "layout", id: "l1", name: "Handover document" }, onClose: fn(), onDuplicated: fn(),
  },
};
export default meta;

type Story = StoryObj<typeof ReportDuplicateDialog>;

const dialog = async () => within(await screen.findByRole("dialog"));
const nameField = (d: ReturnType<typeof within>) => d.getByRole("textbox", { name: "Name" });

export const SuggestsAFreeNameThenCreatesTheCopy: Story = {
  play: async ({ args }) => {
    const d = await dialog();
    await expect(requiredCaptions(document.body)).toEqual(["Name"]);
    await waitFor(() => expect(nameField(d)).toHaveValue("Handover document (copy)"));
    await expect(d.getByRole("combobox", { name: "Copy into" })).toHaveValue("project");
    await expect(args.api.duplicate).toHaveBeenCalledWith(expect.objectContaining({ kind: "layout", source_id: "l1", dry_run: true }));
    await userEvent.click(d.getByRole("button", { name: "Create copy" }));
    await waitFor(() => expect(args.onDuplicated).toHaveBeenCalledWith(expect.objectContaining({ new_id: "new-1", target: "project" })));
    await expect(args.api.duplicate).toHaveBeenLastCalledWith(
      expect.objectContaining({ kind: "layout", source_id: "l1", name: "Handover document (copy)", dry_run: false }),
    );
  },
};

export const ATakenNameIsRefusedBeforeCreating: Story = {
  args: { api: buildDuplicateApi({ taken: ["mine"] }) },
  play: async () => {
    const d = await dialog();
    await waitFor(() => expect(nameField(d)).toHaveValue("Handover document (copy)"));
    await userEvent.clear(nameField(d));
    await userEvent.type(nameField(d), "Mine");
    await expect(await d.findByRole("alert")).toHaveTextContent("A layout with this name already exists here.");
    await expect(d.getByRole("button", { name: "Create copy" })).toBeDisabled();
  },
};

export const AnInheritedNameIsAllowedWithAShadowWarning: Story = {
  args: { api: buildDuplicateApi({ shadows: ["org report"] }) },
  play: async () => {
    const d = await dialog();
    await waitFor(() => expect(nameField(d)).toHaveValue("Handover document (copy)"));
    await userEvent.clear(nameField(d));
    await userEvent.type(nameField(d), "Org report");
    await expect(await d.findByText(/will shadow a report of the same name/)).toBeInTheDocument();
    await expect(d.getByRole("button", { name: "Create copy" })).toBeEnabled();
  },
};

export const CopyingUpListsTheProjectPicturesThatBlockIt: Story = {
  args: { api: buildDuplicateApi({ blockedUp: ["site-plan.png"] }) },
  play: async () => {
    const d = await dialog();
    await waitFor(() => expect(d.getByRole("button", { name: "Create copy" })).toBeEnabled());
    await userEvent.selectOptions(d.getByRole("combobox", { name: "Copy into" }), "organization");
    await expect(await d.findByText("site-plan.png")).toBeInTheDocument();
    await expect(d.getByRole("button", { name: "Create copy" })).toBeDisabled();
    await userEvent.selectOptions(d.getByRole("combobox", { name: "Copy into" }), "project");
    await waitFor(() => expect(d.getByRole("button", { name: "Create copy" })).toBeEnabled());
    await expect(d.queryByText("site-plan.png")).not.toBeInTheDocument();
  },
};

export const CopyingUpWithoutTheOrganisationRightShowsTheRefusal: Story = {
  args: { api: buildDuplicateApi({ refuseUp: true }) },
  play: async () => {
    const d = await dialog();
    await waitFor(() => expect(d.getByRole("button", { name: "Create copy" })).toBeEnabled());
    await userEvent.selectOptions(d.getByRole("combobox", { name: "Copy into" }), "organization");
    await expect(await d.findByRole("alert")).toHaveTextContent("Insufficient permissions in the organisation.");
    await expect(d.getByRole("button", { name: "Create copy" })).toBeDisabled();
  },
};

export const AStarterIsChosenInTheDialog: Story = {
  args: { source: { kind: "starter" } },
  play: async ({ args }) => {
    const d = await dialog();
    await expect(requiredCaptions(document.body)).toEqual(["Starter", "Name"]);
    await expect(d.getByRole("button", { name: "Create copy" })).toBeDisabled();
    const select = await d.findByRole("combobox", { name: "Starter" });
    await waitFor(() => expect(within(select).getAllByRole("option").length).toBeGreaterThan(1));
    await userEvent.selectOptions(select, "business-requirements-document");
    await expect(await d.findByText("Why the work is needed and what the business expects.")).toBeInTheDocument();
    await waitFor(() => expect(nameField(d)).toHaveValue("Business Requirements Document"));
    await userEvent.click(d.getByRole("button", { name: "Create copy" }));
    await waitFor(() => expect(args.onDuplicated).toHaveBeenCalled());
    await expect(args.api.duplicate).toHaveBeenLastCalledWith(
      expect.objectContaining({ kind: "starter", starter_key: "business-requirements-document", dry_run: false }),
    );
  },
};

export const AnOrganisationPageHasNoDestinationChoice: Story = {
  args: { api: buildDuplicateApi({ scope: { kind: "organization", id: "org-1" } }) },
  play: async ({ args }) => {
    const d = await dialog();
    await waitFor(() => expect(nameField(d)).toHaveValue("Handover document (copy)"));
    await expect(d.queryByRole("combobox", { name: "Copy into" })).not.toBeInTheDocument();
    await expect(args.api.duplicate).toHaveBeenCalledWith(expect.objectContaining({ target: "organization" }));
  },
};

export const UnsavedChangesAreSaidNotToBeCopied: Story = {
  args: { note: "Your unsaved changes are not copied: the copy is made from the saved version." },
  play: async () => {
    const d = await dialog();
    await expect(d.getByRole("note")).toHaveTextContent("Your unsaved changes are not copied");
  },
};

export const CancelClosesWithoutCreating: Story = {
  play: async ({ args }) => {
    const d = await dialog();
    await userEvent.click(d.getByRole("button", { name: "Cancel" }));
    await expect(args.onClose).toHaveBeenCalled();
    await expect(args.onDuplicated).not.toHaveBeenCalled();
  },
};
