import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { buildFieldCatalogue } from "../testing/reportLayoutFixtures";
import { aliasesInScope } from "../utils/reportLayoutText";
import { ReportLayoutFieldPicker } from "./ReportLayoutFieldPicker";

/** The field picker of the layout designer: what a `{{...}}` can name at the caret. */
const meta: Meta<typeof ReportLayoutFieldPicker> = {
  title: "Components/ReportLayoutFieldPicker",
  component: ReportLayoutFieldPicker,
  args: { catalogue: buildFieldCatalogue(), aliases: [], onInsert: fn() },
};
export default meta;

type Story = StoryObj<typeof ReportLayoutFieldPicker>;

export const OutsideABlockOffersOnlyGlobalPlaceholders: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Global placeholders only")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Insert {{project_name}}" }));
    await expect(args.onInsert).toHaveBeenCalledWith("{{project_name}}");
  },
};

export const InsideAForEachOffersThatTypesFields: Story = {
  args: { aliases: aliasesInScope("@each requirement sort title as req\n  \n@end\n", 1) },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Insert Status" }));
    await expect(args.onInsert).toHaveBeenCalledWith("{{req.status}}");
    await userEvent.type(canvas.getByRole("textbox", { name: "Find a field" }), "desc");
    await expect(canvas.queryByRole("button", { name: "Insert Status" })).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Insert Description" }));
    await expect(args.onInsert).toHaveBeenLastCalledWith("{{req.description}}");
  },
};

export const NothingMatchingTheFilterSaysSo: Story = {
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
    await userEvent.click(canvas.getByRole("button", { name: "Insert Count" }));
    await expect(args.onInsert).toHaveBeenCalledWith("{{grp.count}}");
    await expect(canvas.getByRole("button", { name: "Insert Value" })).toBeInTheDocument();
  },
};

/** An each over a group's members takes its type from the group; the innermost name is chosen, and another can be picked. */
export const NestedNamesDefaultToTheInnermostAndCanBeSwitched: Story = {
  args: {
    aliases: aliasesInScope(
      "@group pain_point by title as grp\n  @each in grp as pp\n    \n  @end\n@end\n", 2,
    ),
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const name = canvas.getByRole("combobox", { name: "Name to use" });
    await expect(name).toHaveValue("pp");
    await userEvent.click(canvas.getByRole("button", { name: "Insert Severity" }));
    await expect(args.onInsert).toHaveBeenCalledWith("{{pp.severity}}");
    await userEvent.selectOptions(name, "grp");
    await expect(canvas.getByRole("button", { name: "Insert Count" })).toBeInTheDocument();
  },
};

export const ATypeTheScopeDoesNotKnowOffersNoFields: Story = {
  args: { aliases: aliasesInScope("@each decision as d\n\n@end\n", 1) },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("No field matches.")).toBeInTheDocument();
  },
};

/** Closed blocks no longer count and a text block's lines are not read as directives. */
export const AClosedBlockNoLongerContributesItsName: Story = {
  args: { aliases: aliasesInScope("@each requirement as req\n@end\n@text\n@each decision as nope\n@end\n", 6) },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("Global placeholders only")).toBeInTheDocument();
  },
};
