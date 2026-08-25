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
 * blocks the Import button. The mapping/preview step now opens in a
 * `Modal` (roadmap item 506) — a layer portalled to `document.body`, not
 * an inline block inside `canvasElement` — so its content is queried via
 * `within(document.body)`, the same convention the pre-existing Export
 * popover stories below already use for the same reason. */
export const UploadAutoMapsMatchingHeaders: Story = {
  play: async ({ canvasElement, args }) => {
    const csv = "name,component_prefix,category_prefix\nReset password,AUTH,LOG\n";
    const file = new File([csv], "requirements.csv", { type: "text/csv" });
    const input = canvasElement.querySelector('input[type="file"][accept=".csv,text/csv"]') as HTMLInputElement;
    await userEvent.upload(input, file);
    await waitFor(() =>
      expect(within(document.body).getByRole("dialog", { name: "Map your CSV columns" })).toBeInTheDocument()
    );
    const modal = within(document.body).getByRole("dialog", { name: "Map your CSV columns" });
    await waitFor(() => expect(within(modal).getByText("Preview (first 1 of 1 rows)")).toBeInTheDocument());
    // The generic "Match each field..." instructions paragraph always
    // contains "before importing" too — check specifically for the
    // missing-required-fields warning, which ends with "before importing.".
    await expect(within(modal).queryByText(/still need a column or fixed value before importing\.$/)).not.toBeInTheDocument();
    await userEvent.click(within(modal).getByRole("button", { name: /Import 1 row/ }));
    await waitFor(() => expect(args.onImport).toHaveBeenCalledOnce());
  },
};

/** Headers that don't match anything leave required fields unmapped —
 * Import must stay blocked until the user maps them manually. */
export const UploadWithUnmatchedHeadersBlocksImport: Story = {
  play: async ({ canvasElement }) => {
    const csv = "title,area\nReset password,AUTH\n";
    const file = new File([csv], "requirements.csv", { type: "text/csv" });
    const input = canvasElement.querySelector('input[type="file"][accept=".csv,text/csv"]') as HTMLInputElement;
    await userEvent.upload(input, file);
    await waitFor(() =>
      expect(within(document.body).getByRole("dialog", { name: "Map your CSV columns" })).toBeInTheDocument()
    );
    const modal = within(document.body).getByRole("dialog", { name: "Map your CSV columns" });
    await waitFor(() => expect(within(modal).getByText(/Name, Component, Category still need/)).toBeInTheDocument());
    await expect(within(modal).getByRole("button", { name: /Import 1 row/ })).toBeDisabled();
  },
};

/** Roadmap item 506 — the mapping/preview step used to be a permanently-
 * inline `<div className="card stack">` once a file was picked; it's now a
 * `Modal` (`size="lg"`), closable via its own Cancel button (which also
 * clears the picked file, matching the pre-existing `cancel()` behaviour)
 * or the Modal's own ✕/Escape/backdrop affordances. */
export const MappingStepOpensAsAModal: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const csv = "name,component_prefix,category_prefix\nReset password,AUTH,LOG\n";
    const file = new File([csv], "requirements.csv", { type: "text/csv" });
    const input = canvasElement.querySelector('input[type="file"][accept=".csv,text/csv"]') as HTMLInputElement;
    await userEvent.upload(input, file);
    await waitFor(() =>
      expect(within(document.body).getByRole("dialog", { name: "Map your CSV columns" })).toBeInTheDocument()
    );
    const modal = within(document.body).getByRole("dialog", { name: "Map your CSV columns" });
    await waitFor(() => expect(within(modal).getByText("Preview (first 1 of 1 rows)")).toBeInTheDocument());
    // The trigger row (Import CSV / Export) stays visible in the page
    // underneath, unobscured except by the Modal's own backdrop — proving
    // this is a layer on top, not a page reflow.
    await expect(canvas.getByRole("button", { name: "Export" })).toBeInTheDocument();

    await userEvent.click(within(modal).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(within(document.body).queryByRole("dialog", { name: "Map your CSV columns" })).not.toBeInTheDocument());
  },
};

/** Roadmap item 507 — component/category/level/target_version can each be
 * set to one fixed value applied to every imported row instead of mapped
 * from a CSV column, defaulting to column-mapped (the only prior
 * behaviour) so an existing CSV/workflow is unaffected. A CSV with only a
 * `name` column, plus every fixable field set to a fixed value, still
 * produces a valid, importable batch — and the preview reflects the same
 * fixed value on every row, not just the first. */
export const FixedValueToggleAppliesToEveryRow: Story = {
  play: async ({ canvasElement, args }) => {
    const csv = "name\nFirst requirement\nSecond requirement\n";
    const file = new File([csv], "names-only.csv", { type: "text/csv" });
    const input = canvasElement.querySelector('input[type="file"][accept=".csv,text/csv"]') as HTMLInputElement;
    await userEvent.upload(input, file);
    await waitFor(() =>
      expect(within(document.body).getByRole("dialog", { name: "Map your CSV columns" })).toBeInTheDocument()
    );
    const modal = within(document.body).getByRole("dialog", { name: "Map your CSV columns" });
    await waitFor(() => expect(within(modal).getByText("Preview (first 2 of 2 rows)")).toBeInTheDocument());

    // Component/Category are required and have no CSV column to map — the
    // import stays blocked until they're each given a fixed value.
    const importButton = within(modal).getByRole("button", { name: /Import 2 row/ });
    await expect(importButton).toBeDisabled();

    await userEvent.click(within(modal).getByLabelText("Use the same component for every row"));
    await userEvent.selectOptions(within(modal).getByLabelText("Fixed component"), "AUTH");
    await userEvent.click(within(modal).getByLabelText("Use the same category for every row"));
    // Fixing the component first narrows the category options to that
    // component's own — only "LOG (Authentication)" is offered here.
    await userEvent.selectOptions(within(modal).getByLabelText("Fixed category"), "LOG");
    await userEvent.click(within(modal).getByLabelText("Use the same level for every row"));
    await userEvent.selectOptions(within(modal).getByLabelText("Fixed level"), "recommended");

    await expect(importButton).toBeEnabled();
    // Both preview rows show the same fixed component/category/level —
    // the raw wire value ("recommended"), the same thing a mapped column's
    // cell would show, not the `<select>`'s own human-readable label —
    // proving the constant is applied per row, not just to whichever row
    // happened to have a mapped column.
    const previewRows = within(modal).getAllByRole("row").slice(-2);
    for (const row of previewRows) {
      await expect(within(row).getByText("AUTH")).toBeInTheDocument();
      await expect(within(row).getByText("LOG")).toBeInTheDocument();
      await expect(within(row).getByText("recommended")).toBeInTheDocument();
    }

    await userEvent.click(importButton);
    await waitFor(() => expect(args.onImport).toHaveBeenCalledOnce());
    const onImportMock = args.onImport as unknown as ReturnType<typeof fn<(file: File) => Promise<void>>>;
    const uploadedFile = onImportMock.mock.calls[0][0];
    const uploadedText = await uploadedFile.text();
    // Every data row (not just the first) carries the fixed values — the
    // actual wire contract the backend's canonical-CSV import endpoint
    // consumes (see `backend/tests/test_requirement_csv_export_import.py`'s
    // own pinning test for the backend half of this).
    const dataLines = uploadedText.trim().split("\n").slice(1);
    await expect(dataLines).toHaveLength(2);
    for (const line of dataLines) {
      await expect(line).toContain("AUTH");
      await expect(line).toContain("LOG");
      await expect(line).toContain("recommended");
    }
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
    await waitFor(() =>
      expect(within(document.body).getByRole("dialog", { name: "Map your CSV columns" })).toBeInTheDocument()
    );
    const modal = within(document.body).getByRole("dialog", { name: "Map your CSV columns" });
    await waitFor(() => expect(within(modal).getByText("Preview (first 1 of 1 rows)")).toBeInTheDocument());
    await userEvent.click(within(modal).getByRole("button", { name: /Import 1 row/ }));
    await waitFor(() => expect(args.onImport).toHaveBeenCalledOnce());
  },
};

export const LightTheme: Story = { globals: { theme: "light" } };
export const DarkTheme: Story = { globals: { theme: "dark" } };
