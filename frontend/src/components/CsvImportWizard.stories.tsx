import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import { buildCategory, buildComponent, buildStage } from "../testing/storybook-helpers";
import { CsvImportWizard } from "./CsvImportWizard";

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
    await expect(canvas.getByText("Export CSV")).toBeInTheDocument();
    await expect(canvas.queryByText("Map your CSV columns")).not.toBeInTheDocument();
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
    await userEvent.click(canvas.getByRole("button", { name: /Export CSV/ }));
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

export const LightTheme: Story = { globals: { theme: "light" } };
export const DarkTheme: Story = { globals: { theme: "dark" } };
