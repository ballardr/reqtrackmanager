import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { buildFieldCatalogue } from "../testing/reportLayoutFixtures";
import { aliasesInScope } from "../utils/reportLayoutText";
import { ReportLayoutFieldPicker } from "./ReportLayoutFieldPicker";

/** The field picker of the layout designer: one searchable, filterable list of what a `{{...}}` can name at the caret. */
const meta: Meta<typeof ReportLayoutFieldPicker> = {
  title: "Components/ReportLayoutFieldPicker",
  component: ReportLayoutFieldPicker,
  args: { catalogue: buildFieldCatalogue(), aliases: [], onInsert: fn() },
};
export default meta;

type Story = StoryObj<typeof ReportLayoutFieldPicker>;

/** Outside any block the list holds only the report and project placeholders, with readable labels. */
export const OutsideABlockOffersOnlyReportAndProjectPlaceholders: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Project name")).toBeInTheDocument();
    await expect(canvas.queryByRole("combobox", { name: "From" })).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Insert {{project_name}}" }));
    await expect(args.onInsert).toHaveBeenCalledWith("{{project_name}}");
  },
};

/** Inside a For each the type's fields join the same list, innermost name first, each saying where it comes from. */
export const InsideAForEachTheTypesFieldsJoinTheProjectPlaceholders: Story = {
  args: { aliases: aliasesInScope("@each requirement sort title as req\n  \n@end\n", 1) },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Insert {{project_name}}" })).toBeInTheDocument();
    await expect(canvas.getAllByText("req (Requirement)").length).toBeGreaterThan(0);
    await userEvent.click(canvas.getByRole("button", { name: "Insert {{req.status}}" }));
    await expect(args.onInsert).toHaveBeenCalledWith("{{req.status}}");
  },
};

/** One search covers fields and placeholders alike. */
export const SearchNarrowsEveryEntry: Story = {
  args: { aliases: aliasesInScope("@each requirement sort title as req\n  \n@end\n", 1) },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByRole("textbox", { name: "Find a field" }), "desc");
    await expect(canvas.queryByRole("button", { name: "Insert {{req.status}}" })).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Insert {{req.description}}" }));
    await expect(args.onInsert).toHaveBeenLastCalledWith("{{req.description}}");
    await userEvent.clear(canvas.getByRole("textbox", { name: "Find a field" }));
    await userEvent.type(canvas.getByRole("textbox", { name: "Find a field" }), "generated");
    await expect(canvas.getByRole("button", { name: "Insert {{generated_on}}" })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Insert {{req.description}}" })).not.toBeInTheDocument();
  },
};

/** The From filter narrows to the report and project values, or to one name in scope. */
export const TheFromFilterNarrowsToOneSource: Story = {
  args: { aliases: aliasesInScope("@each requirement sort title as req\n  \n@end\n", 1) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "From" }), "Report and project");
    await expect(canvas.queryByRole("button", { name: "Insert {{req.status}}" })).not.toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Insert {{project_name}}" })).toBeInTheDocument();
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "From" }), "req");
    await expect(canvas.getByRole("button", { name: "Insert {{req.status}}" })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Insert {{project_name}}" })).not.toBeInTheDocument();
  },
};

/** A text field in which equations are drawn says so beside its kind; an ordinary text field does not. */
export const AMathCapableFieldIsMarked: Story = {
  args: { aliases: aliasesInScope("@each requirement sort title as req\n  \n@end\n", 1) },
  play: async ({ canvasElement }) => {
    const row = within(canvasElement).getByRole("button", { name: "Insert {{req.description}}" }).closest("li") as HTMLElement;
    await expect(within(row).getByText("text, equations drawn")).toBeInTheDocument();
    const status = within(canvasElement).getByRole("button", { name: "Insert {{req.status}}" }).closest("li") as HTMLElement;
    await expect(within(status).queryByText(/equations drawn/)).not.toBeInTheDocument();
  },
};

export const NothingMatchingTheSearchSaysSo: Story = {
  args: { aliases: aliasesInScope("@each requirement as req\n\n@end\n", 1) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByRole("textbox", { name: "Find a field" }), "zzz");
    await expect(canvas.getByText("No field matches.")).toBeInTheDocument();
  },
};

export const InsideAGroupOffersValueAndCount: Story = {
  args: { aliases: aliasesInScope("@group requirement by status as grp\n\n@end\n", 1) },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Insert {{grp.count}}" }));
    await expect(args.onInsert).toHaveBeenCalledWith("{{grp.count}}");
    await expect(canvas.getByRole("button", { name: "Insert {{grp.value}}" })).toBeInTheDocument();
  },
};

/** Nested names are all in the list, the innermost first, and the From filter picks one. */
export const NestedNamesAreAllListedInnermostFirst: Story = {
  args: {
    aliases: aliasesInScope("@group pain_point by title as grp\n  @each in grp as pp\n    \n  @end\n@end\n", 2),
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Insert {{pp.severity}}" }));
    await expect(args.onInsert).toHaveBeenCalledWith("{{pp.severity}}");
    await expect(canvas.getByRole("button", { name: "Insert {{grp.count}}" })).toBeInTheDocument();
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "From" }), "grp");
    await expect(canvas.queryByRole("button", { name: "Insert {{pp.severity}}" })).not.toBeInTheDocument();
  },
};

/** A type the scope does not know adds no fields; the report and project values are still there. */
export const ATypeTheScopeDoesNotKnowAddsNoFields: Story = {
  args: { aliases: aliasesInScope("@each decision as d\n\n@end\n", 1) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Insert {{project_name}}" })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: /Insert \{\{d\./ })).not.toBeInTheDocument();
  },
};

/** Closed blocks no longer count and a text block's lines are not read as directives. */
export const AClosedBlockNoLongerContributesItsName: Story = {
  args: { aliases: aliasesInScope("@each requirement as req\n@end\n@text\n@each decision as nope\n@end\n", 6) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("option", { name: "req" })).not.toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Insert {{project_name}}" })).toBeInTheDocument();
  },
};
