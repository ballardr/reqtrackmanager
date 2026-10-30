import type { Decorator, Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, screen, userEvent, waitFor, within } from "storybook/test";
import { MemoryRouter } from "react-router-dom";

import { buildCopyApi } from "../testing/reportCopyFixtures";
import { requiredCaptions } from "../testing/requiredMarkers";
import { buildUser, withStatefulAuth, withToast } from "../testing/storybook-helpers";
import { ReportCopyDialog } from "./ReportCopyDialog";

const withRouter: Decorator = (Story) => <MemoryRouter><Story /></MemoryRouter>;

const ITEMS = { layout_ids: ["l1", "l2"], pack_ids: ["p1"], folders: ["Board"], placement_keys: [] };
const NAMES = { l1: "Handover document", l2: "Monthly status", p1: "Board pack", Board: "Board" };

/**
 * Copies the reports ticked in a project's Report setup into another project: choose the project and how to settle a
 * name it already uses, preview what would happen, then copy. Nothing is replaced.
 */
const meta: Meta<typeof ReportCopyDialog> = {
  title: "Components/Reports/ReportCopyDialog",
  component: ReportCopyDialog,
  decorators: [withToast(), withStatefulAuth(buildUser({ ui_preferences: {} })), withRouter],
  args: { sourceProjectId: "project-1", items: ITEMS, onClose: fn(), onCopied: fn(), api: buildCopyApi({ names: NAMES }) },
};
export default meta;

type Story = StoryObj<typeof ReportCopyDialog>;

const dialog = async () => within(await screen.findByRole("dialog"));
const choose = async (d: ReturnType<typeof within>, name: string) => {
  const select = await d.findByRole("combobox", { name: /Copy into/ });
  await waitFor(() => expect(select).toBeEnabled());
  await userEvent.selectOptions(select, name);
};

export const PreviewThenCopy: Story = {
  args: { api: buildCopyApi({ names: NAMES, renamed: ["l2"], warnings: { l1: ["It uses report parts of modules that are off in the target project: Risk Management."] } }) },
  play: async ({ args }) => {
    const d = await dialog();
    await expect(requiredCaptions(document.body)).toEqual(["Copy into"]);
    await expect(d.getByRole("button", { name: "Preview" })).toBeDisabled();
    await choose(d, "Apollo");
    await userEvent.click(d.getByRole("button", { name: "Preview" }));
    await expect(await d.findByText("Monthly status → Monthly status (copy)")).toBeInTheDocument();
    await expect(d.getByText(/modules that are off in the target project/)).toBeInTheDocument();
    await expect(args.api.copy).toHaveBeenLastCalledWith("project-2", expect.objectContaining({ dry_run: true, on_conflict: "rename", ...ITEMS }));
    await userEvent.click(d.getByRole("button", { name: "Copy 4 items" }));
    await expect(await d.findByRole("status")).toHaveTextContent("4 items copied to Apollo.");
    await expect(args.api.copy).toHaveBeenLastCalledWith("project-2", expect.objectContaining({ dry_run: false }));
    await expect(d.getByRole("link", { name: "Open Apollo's report setup" })).toHaveAttribute("href", "/projects/project-2/admin/reportSetup");
    await expect(args.onCopied).toHaveBeenCalled();
    await expect(d.queryByRole("button", { name: /^Copy / })).not.toBeInTheDocument();
  },
};

export const SkippingATakenNameLeavesItOut: Story = {
  args: { api: buildCopyApi({ names: NAMES, renamed: ["l2"] }) },
  play: async ({ args }) => {
    const d = await dialog();
    await choose(d, "Apollo");
    await userEvent.selectOptions(d.getByRole("combobox", { name: /If the project already has one/ }), "skip");
    await userEvent.click(d.getByRole("button", { name: "Preview" }));
    await expect(await d.findByText("Skip: name already used")).toBeInTheDocument();
    await expect(d.getByRole("button", { name: "Copy 3 items" })).toBeInTheDocument();
    await expect(args.api.copy).toHaveBeenLastCalledWith("project-2", expect.objectContaining({ on_conflict: "skip" }));
  },
};

export const ChangingTheTargetDiscardsThePreview: Story = {
  play: async () => {
    const d = await dialog();
    await choose(d, "Apollo");
    await userEvent.click(d.getByRole("button", { name: "Preview" }));
    await d.findByText("Handover document");
    await choose(d, "Apollo phase 2");
    await expect(d.queryByText("Handover document")).not.toBeInTheDocument();
    await expect(d.getByRole("button", { name: "Preview" })).toBeEnabled();
  },
};

export const OneItemIsNamedInTheTitle: Story = {
  args: { items: { layout_ids: ["l1"], pack_ids: [], folders: [], placement_keys: [] } },
  play: async () => {
    await expect(await screen.findByRole("dialog", { name: "Copy 1 item to another project" })).toBeInTheDocument();
  },
};

export const WithNowhereToCopyToItSaysSo: Story = {
  args: { api: buildCopyApi({ targets: [] }) },
  play: async () => {
    const d = await dialog();
    await expect(await d.findByText(/no other project in this organisation where you can manage reports/)).toBeInTheDocument();
    await expect(d.getByRole("combobox", { name: /Copy into/ })).toBeDisabled();
  },
};

export const ARefusedCopyShowsTheError: Story = {
  args: {
    api: {
      ...buildCopyApi(),
      copy: fn(async () => { throw new Error("You cannot manage reports in the source project."); }),
    },
  },
  play: async () => {
    const d = await dialog();
    await choose(d, "Apollo");
    await userEvent.click(d.getByRole("button", { name: "Preview" }));
    await expect(await d.findByText("You cannot manage reports in the source project.")).toBeInTheDocument();
  },
};

export const CancelClosesWithoutCopying: Story = {
  play: async ({ args }) => {
    const d = await dialog();
    await userEvent.click(d.getByRole("button", { name: "Cancel" }));
    await expect(args.onClose).toHaveBeenCalled();
    await expect(args.api.copy).not.toHaveBeenCalled();
  },
};
