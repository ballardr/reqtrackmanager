import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import type { ReportContentEntry, ReportTypeOption } from "../api/types";
import { ReportContentEditor } from "./ReportContentEditor";
import type { InheritedContent } from "./reportContentInheritance";
import { describeContentSource, inheritedFromEffective } from "./reportContentInheritance";

const reportTypes: ReportTypeOption[] = [
  { key: "requirements", title: "Requirements report", module_name: null },
  { key: "decisions.r1", title: "Decision log", module_name: "Decision Management" },
];

function Interactive({
  initial = [], inherited,
}: { initial?: ReportContentEntry[]; inherited?: Record<string, InheritedContent> }) {
  const [value, setValue] = useState<ReportContentEntry[]>(initial);
  return (
    <div>
      <ReportContentEditor idPrefix="story" reportTypes={reportTypes} value={value} onChange={setValue} inherited={inherited} />
      <pre data-testid="value">{JSON.stringify(value)}</pre>
    </div>
  );
}

const meta: Meta<typeof Interactive> = {
  title: "Components/ReportContentEditor",
  component: Interactive,
};
export default meta;

type Story = StoryObj<typeof Interactive>;

/** A drop-down of report types, led by "All reports"; the placeholders the content may use are listed. */
export const DropdownOfReportTypes: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const options = within(canvas.getByLabelText("Report type")).getAllByRole("option").map((o) => o.textContent);
    await expect(options).toEqual(["All reports", "Requirements report", "Decision log"]);
    await expect(canvas.getByText(/No content set at this level\./)).toBeInTheDocument();
    await userEvent.click(canvas.getByText("Placeholders"));
    for (const token of ["{{project_name}}", "{{report_title}}", "{{generated_on}}", "{{organisation}}"]) {
      await expect(canvas.getByText(token)).toBeInTheDocument();
    }
  },
};

/** Content is kept per report type: switching type shows each type's own entry, and a type left
 * blank is absent from the value (the server stores no empty rows). */
export const EditingOneTypeLeavesTheOthers: Story = {
  args: {
    initial: [{ report_key: "requirements", intro: "Requirements intro", chapters: [], appendices: [] }],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(canvas.getByLabelText("Report type"), "decisions.r1");
    await userEvent.click(canvas.getAllByRole("button", { name: "Add chapter" })[0]);
    await userEvent.type(canvas.getAllByPlaceholderText("Chapter title")[0], "Decision criteria");
    const value = JSON.parse(canvas.getByTestId("value").textContent ?? "[]") as ReportContentEntry[];
    await expect(value.map((e) => e.report_key).sort()).toEqual(["decisions.r1", "requirements"]);
    await expect(value.find((e) => e.report_key === "requirements")?.intro).toBe("Requirements intro");
    await expect(canvas.getByText(/Content set for: .*Requirements report/)).toBeInTheDocument();
    // The list marks the types that hold content.
    await expect(within(canvas.getByLabelText("Report type")).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "All reports", "Requirements report (has content)", "Decision log (has content)",
    ]);

    // Removing the only chapter blanks the entry, which drops it from the value.
    await userEvent.click(canvas.getAllByRole("button", { name: "Delete chapter" })[0]);
    const after = JSON.parse(canvas.getByTestId("value").textContent ?? "[]") as ReportContentEntry[];
    await expect(after.map((e) => e.report_key)).toEqual(["requirements"]);
  },
};

const inheritedRequirements: InheritedContent = {
  intro: { label: "Inherited from Parent Programme", preview: "The parent's introduction." },
  chapters: { label: "Organisation default (Acme)", preview: "Scope · Assumptions" },
};

/** Where a project's blank field gets its content from, and the way back once it has set its own. */
export const InheritedContentIsNamedAndResettable: Story = {
  args: { inherited: { requirements: inheritedRequirements } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(canvas.getByLabelText("Report type"), "requirements");
    await expect(canvas.getByText("Inherited from Parent Programme")).toBeInTheDocument();
    await expect(canvas.getByText("The parent's introduction.")).toBeInTheDocument();
    await expect(canvas.getByText("Organisation default (Acme)")).toBeInTheDocument();
    // Nothing inherited for appendices.
    await expect(canvas.getByText("Nothing is inherited, so the report prints none.")).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Use inherited" })).not.toBeInTheDocument();

    await userEvent.type(canvas.getAllByRole("textbox")[0], "Our own intro");
    await expect(canvas.queryByText("The parent's introduction.")).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Use inherited" }));
    await expect(canvas.getByText("The parent's introduction.")).toBeInTheDocument();
  },
};

/** The effective-content response is turned into the inherited hints; a value the project owns is not "inherited". */
export const SourcesAreDescribedInWords: Story = {
  render: () => <span />,
  play: async () => {
    const source = (scope_type: "template" | "project" | "organization" | "project_summary", scope_name: string) => ({
      scope_type, scope_id: scope_type === "project" ? "parent" : "x", scope_name, report_key: "requirements",
    });
    await expect(describeContentSource(source("organization", "Acme"))).toBe("Organisation default (Acme)");
    await expect(describeContentSource(source("template", "Board Pack"))).toBe("Template Board Pack");
    await expect(describeContentSource(source("project_summary", "Atlas"))).toBe("Atlas description");
    await expect(describeContentSource(source("project", "Parent"))).toBe("Inherited from Parent");

    const hints = inheritedFromEffective({
      report_key: "requirements", intro: "Own", chapters: [{ title: "A", body: "" }, { title: "B", body: "" }], appendices: [],
      intro_source: { ...source("project", "Me"), scope_id: "me" },
      chapters_source: source("project", "Parent"), appendices_source: null,
    }, "me");
    await expect(hints.intro).toBeUndefined();
    await expect(hints.chapters).toEqual({ label: "Inherited from Parent", preview: "A · B" });
    await expect(hints.appendices).toBeUndefined();
  },
};
