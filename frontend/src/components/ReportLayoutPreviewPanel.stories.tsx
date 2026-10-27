import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { buildReportVariable } from "../testing/reportFixtures";
import { buildDocumentPreview, buildLayoutApi, buildSheetPreview } from "../testing/reportLayoutFixtures";
import { ReportLayoutPreviewPanel } from "./ReportLayoutPreviewPanel";

/** The live preview of the layout designer: runs the draft as the signed-in person and stores nothing. */
const meta: Meta<typeof ReportLayoutPreviewPanel> = {
  title: "Components/ReportLayoutPreviewPanel",
  component: ReportLayoutPreviewPanel,
  args: { api: buildLayoutApi(), text: "@layout document\n", name: "Requirements", disabled: false },
};
export default meta;

type Story = StoryObj<typeof ReportLayoutPreviewPanel>;

export const ADocumentShowsInAFullySandboxedFrame: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Run preview" }));
    const frame = await canvas.findByTitle("Report preview");
    // An empty sandbox attribute grants nothing: no scripts, no same-origin access, no forms, no popups.
    await expect(frame).toHaveAttribute("sandbox", "");
    await expect(frame).toHaveAttribute("srcdoc", expect.stringContaining("Requirements of Atlas"));
    await expect(args.api.preview).toHaveBeenCalledWith({ text: "@layout document\n", name: "Requirements", include_children: false, project_ids: undefined });
    await expect(canvas.getByRole("status")).toHaveTextContent("3 records read across 1 project in 12 ms.");
  },
};

const VARIABLE_TEXT = "@layout document\n@var categories enum list from requirement.category\n\n@heading Requirements\n";

/** The draft's variables become a form; the preview waits for a required one and sends the chosen values. */
export const TheDraftsVariablesAreAskedForBeforeThePreviewRuns: Story = {
  args: {
    text: VARIABLE_TEXT,
    api: buildLayoutApi([], { draftVariables: fn(async () => ({ ok: true, variables: [buildReportVariable()], errors: [] })) }),
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("button", { name: /Categories/ })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Run preview" })).toBeDisabled();
    await expect(canvas.getByText("Choose a value for Categories to run this report.")).toBeInTheDocument();

    await userEvent.click(canvas.getByRole("button", { name: /Categories/ }));
    await userEvent.click(await within(document.body).findByRole("checkbox", { name: "Usability" }));
    await userEvent.click(canvas.getByRole("button", { name: "Run preview" }));

    await waitFor(() => expect(args.api.preview).toHaveBeenCalledWith(expect.objectContaining({ variables: { categories: ["Usability"] } })));
    // Only the declarations were sent to build the form, never the whole draft.
    await expect(args.api.draftVariables).toHaveBeenCalledWith("@layout document\n@var categories enum list from requirement.category\n");
  },
};

export const ATablePreviewShowsCappedSheetsWithTheRealCount: Story = {
  args: { api: buildLayoutApi([], { preview: async () => buildSheetPreview() }) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Run preview" }));
    const sheet = await canvas.findByRole("region", { name: "Requirements" });
    await expect(within(sheet).getByText("Brake pads")).toBeInTheDocument();
    await expect(within(sheet).getByText("Showing the first 2 of 250 rows.")).toBeInTheDocument();
  },
};

export const WarningsAreListed: Story = {
  args: { api: buildLayoutApi([], { preview: async () => buildDocumentPreview({ warnings: ["A read was capped at 5000 records."] }) }) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Run preview" }));
    await expect(await canvas.findByRole("list", { name: "Warnings" })).toHaveTextContent("A read was capped at 5000 records.");
  },
};

export const AProjectPreviewCanIncludeChildProjects: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("switch", { name: "Include child projects" }));
    await userEvent.click(canvas.getByRole("button", { name: "Run preview" }));
    await waitFor(() => expect(args.api.preview).toHaveBeenCalledWith(expect.objectContaining({ include_children: true })));
  },
};

export const AnOrganisationPreviewCanChooseProjects: Story = {
  args: {
    api: buildLayoutApi([], { kind: "organization" }),
    projectOptions: [{ value: "p1", label: "Atlas" }, { value: "p2", label: "Borealis" }],
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("switch", { name: "Include child projects" })).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: /Projects/ }));
    await userEvent.click(await within(document.body).findByRole("checkbox", { name: "Borealis" }));
    await userEvent.click(canvas.getByRole("button", { name: "Run preview" }));
    await waitFor(() => expect(args.api.preview).toHaveBeenCalledWith(expect.objectContaining({ project_ids: ["p2"] })));
  },
};

export const TextWithProblemsCannotBePreviewed: Story = {
  args: { disabled: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Run preview" })).toBeDisabled();
    await expect(canvas.getByText("Fix the problems in the text to preview it.")).toBeInTheDocument();
  },
};

export const ARefusedRunShowsTheReason: Story = {
  args: { api: buildLayoutApi([], { preview: async () => { throw new Error("The report is too large. Narrow the layout."); } }) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Run preview" }));
    await expect(await canvas.findByRole("alert")).toHaveTextContent("The report is too large. Narrow the layout.");
  },
};

/** A result belongs to the text it was run on: once the text changes it is no longer shown as the preview. */
export const ChangingTheTextDropsTheStaleResult: Story = {
  render: function Render(args) {
    return <StaleHarness {...args} />;
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Run preview" }));
    await canvas.findByTitle("Report preview");
    await userEvent.click(canvas.getByRole("button", { name: "Edit the text" }));
    await waitFor(() => expect(canvas.queryByTitle("Report preview")).not.toBeInTheDocument());
  },
};

function StaleHarness(args: React.ComponentProps<typeof ReportLayoutPreviewPanel>) {
  const [text, setText] = useState(args.text);
  return (
    <>
      <button type="button" onClick={() => setText(`${text}more\n`)}>Edit the text</button>
      <ReportLayoutPreviewPanel {...args} text={text} />
    </>
  );
}
