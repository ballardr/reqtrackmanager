import type { Meta, StoryObj } from "@storybook/react-vite";
import { useRef, type ComponentProps } from "react";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import { buildCategory, buildComponent, buildStage } from "../testing/storybook-helpers";
import { CsvImportWizard, type CsvImportWizardHandle } from "./CsvImportWizard";

const component = buildComponent({ id: "c1", prefix: "AUTH" });
const category = buildCategory({ id: "cat1", component_id: "c1", prefix: "LOG" });
const stage = buildStage({ id: "s1", name: "Build" });

const meta: Meta<typeof CsvImportWizard> = {
  title: "Components/CsvImportWizard",
  component: CsvImportWizard,
  args: {
    projectId: "project-1",
    projectName: "Atlas Platform",
    components: [component],
    categories: [category],
    stages: [stage],
    customFields: [],
    importing: false,
    onImport: fn().mockResolvedValue(undefined),
  },
};
export default meta;

type Story = StoryObj<typeof CsvImportWizard>;

export const InitialState: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Import CSV")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Export" })).toBeInTheDocument();
    await expect(canvas.queryByText("Export CSV")).not.toBeInTheDocument();
    await expect(canvas.queryByText("Map your CSV columns")).not.toBeInTheDocument();
  },
};

/** "Export CSV" and "Download template" used to sit as two permanently-
 * visible, unlabelled buttons next to each other — the same "two blocks
 * competing for the same job" shape Principle 5 was written against for
 * create flows, just for downloads instead. They now live behind one
 * "Export" popover, the same shape `RequirementsPage`'s own "+ New
 * requirement" trigger uses for Add one / Import from CSV. */
export const ExportMenuOffersCsvAndTemplate: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Export" }));
    const menu = within(document.body).getByRole("dialog", { name: "Export" });
    await expect(within(menu).getByRole("button", { name: "Export CSV" })).toBeInTheDocument();
    await expect(within(menu).getByRole("button", { name: "Download template" })).toBeInTheDocument();
  },
};

/** Uploading a CSV whose headers already match the canonical field names
 * (case-insensitively) — `guessMapping` should auto-map them, and the
 * required fields (Name/Component/Category) end up pre-filled so nothing
 * blocks the Import button. */
export const UploadAutoMapsMatchingHeaders: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const csv = "name,component_prefix,category_prefix\nReset password,AUTH,LOG\n";
    const file = new File([csv], "requirements.csv", { type: "text/csv" });
    const input = canvasElement.querySelector('input[type="file"][accept=".csv,text/csv"]') as HTMLInputElement;
    await userEvent.upload(input, file);
    await waitFor(() => expect(canvas.getByText("Map your CSV columns")).toBeInTheDocument());
    await expect(canvas.getByText("Preview (first 1 of 1 rows)")).toBeInTheDocument();
    // The generic "Match each field..." instructions paragraph always
    // contains "before importing" too — check specifically for the
    // missing-required-fields warning, which starts with "Map ".
    await expect(canvas.queryByText(/^Map .+ before importing\.$/)).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: /Import 1 row/ }));
    await waitFor(() => expect(args.onImport).toHaveBeenCalledOnce());
  },
};

/** Headers that don't match anything leave required fields unmapped —
 * Import must stay blocked until the user maps them manually. */
export const UploadWithUnmatchedHeadersBlocksImport: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const csv = "title,area\nReset password,AUTH\n";
    const file = new File([csv], "requirements.csv", { type: "text/csv" });
    const input = canvasElement.querySelector('input[type="file"][accept=".csv,text/csv"]') as HTMLInputElement;
    await userEvent.upload(input, file);
    await waitFor(() => expect(canvas.getByText("Map your CSV columns")).toBeInTheDocument());
    await expect(canvas.getByText(/Name, Component, Category before importing/)).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: /Import 1 row/ })).toBeDisabled();
  },
};

export const ExportDownloadsServerCsv: Story = {
  beforeEach: () => {
    spyOn(api, "getForBlob").mockResolvedValue(new Blob(["name\n"], { type: "text/csv" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Export" }));
    const menu = within(document.body).getByRole("dialog", { name: "Export" });
    await userEvent.click(within(menu).getByRole("button", { name: /Export CSV/ }));
    await waitFor(() => expect(api.getForBlob).toHaveBeenCalledWith("/api/v1/projects/project-1/requirements/export"));
  },
};

export const ImportingState: Story = {
  args: { importing: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Importing…")).toBeInTheDocument();
  },
};

/** `RequirementsPage`'s single "+ Add requirement" split trigger opens
 * this component's file picker via `openFilePicker()` rather than its own
 * "Import CSV" button, which `showImportTrigger={false}` hides — Export
 * and the template download stay visible either way, since those are
 * downloads, not part of the create flow the split trigger consolidates. */
function HiddenTriggerHarness(props: ComponentProps<typeof CsvImportWizard>) {
  const ref = useRef<CsvImportWizardHandle>(null);
  return (
    <div className="stack">
      <button onClick={() => ref.current?.openFilePicker()}>Open file picker externally</button>
      <CsvImportWizard {...props} ref={ref} showImportTrigger={false} />
    </div>
  );
}

export const HiddenImportTriggerOpensViaRef: Story = {
  render: (args) => <HiddenTriggerHarness {...args} />,
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByText("Import CSV")).not.toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Export" })).toBeInTheDocument();

    const csv = "name,component_prefix,category_prefix\nReset password,AUTH,LOG\n";
    const file = new File([csv], "requirements.csv", { type: "text/csv" });
    const input = canvasElement.querySelector('input[type="file"][accept=".csv,text/csv"]') as HTMLInputElement;
    await userEvent.upload(input, file);
    await waitFor(() => expect(canvas.getByText("Map your CSV columns")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: /Import 1 row/ }));
    await waitFor(() => expect(args.onImport).toHaveBeenCalledOnce());
  },
};

export const LightTheme: Story = { globals: { theme: "light" } };
export const DarkTheme: Story = { globals: { theme: "dark" } };
