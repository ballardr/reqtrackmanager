import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { buildReportResult } from "../testing/reportFixtures";
import { statBlockViolations } from "../testing/statBlockGeometry";
import { ReportViewer } from "./ReportViewer";

const meta: Meta<typeof ReportViewer> = {
  title: "Components/Reports/ReportViewer",
  component: ReportViewer,
  args: { result: buildReportResult() },
};
export default meta;

type Story = StoryObj<typeof ReportViewer>;

/** Notes, headline metrics and each section as a table; a gap section is marked with its count. */
export const SectionsMetricsAndGapBadge: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Covers this project only.")).toBeInTheDocument();
    await expect(canvas.getByText("Unowned")).toBeInTheDocument();
    const items = within(canvas.getByRole("region", { name: "Items" }));
    await expect(items.getByRole("columnheader", { name: "Status" })).toBeInTheDocument();
    await expect(items.getByText("Beta")).toBeInTheDocument();
    await expect(canvas.getByText("Needs attention · 1")).toBeInTheDocument();
    await expect(canvas.getByText("Nobody owns these.")).toBeInTheDocument();
  },
};

/** A gap table with no rows reads as a good thing ("None"), not a problem. */
export const EmptyGapSectionReadsAsNone: Story = {
  args: {
    result: buildReportResult({
      sections: [{ key: "gaps", title: "Unowned items", columns: ["Name"], rows: [], note: "", gap: true }],
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("None")).toBeInTheDocument();
    await expect(canvas.getByText("No rows.")).toBeInTheDocument();
    await expect(canvas.queryByText(/Needs attention/)).not.toBeInTheDocument();
  },
};

/** No in-scope project has the feature on: one explicit message, no empty tables. */
export const NothingToReportOn: Story = {
  args: { result: buildReportResult({ eligible_projects: 0 }) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("status")).toHaveTextContent("Nothing to report on");
    await expect(canvas.queryByRole("table")).not.toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...SectionsMetricsAndGapBadge, globals: { theme: "light" } };
export const DarkTheme: Story = { ...SectionsMetricsAndGapBadge, globals: { theme: "dark" } };

/** A pack's figures arrive with a `group`: one card per source report, gap figures flagged, and a section marked
 * `screen: false` (the flat export-only table) is not shown. */
export const GroupedPackFigures: Story = {
  args: {
    result: buildReportResult({
      metrics: [
        { label: "Open Pain Points (excluding intentional)", value: 3, group: "Pain Point prioritisation" },
        { label: "Blockers", value: 1, gap: true, group: "Pain Point prioritisation" },
        { label: "Not scored", value: 0, gap: true, group: "Pain Point prioritisation" },
        { label: "Overdue", value: 2, gap: true, group: "Open Question register" },
        { label: "Versions in range", value: 29, group: "Strategy change history" },
      ],
      sections: [
        { key: "headline", title: "Headline figures", columns: ["Report"], rows: [["x"]], note: "", gap: false, screen: false },
        { key: "items", title: "Items", columns: ["Name"], rows: [["Alpha"]], note: "", gap: false },
      ],
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const pp = within(canvas.getByRole("region", { name: "Pain Point prioritisation" }));
    await expect(pp.getByText("Blockers")).toBeInTheDocument();
    await expect(pp.getByText("Needs attention · 1")).toBeInTheDocument();
    await expect(canvas.queryByRole("region", { name: "Headline figures" })).not.toBeInTheDocument();
    await expect(canvas.getByRole("region", { name: "Items" })).toBeInTheDocument();
    await expect(statBlockViolations(canvasElement)).toEqual([]);
  },
};
