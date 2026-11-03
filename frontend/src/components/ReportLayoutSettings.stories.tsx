import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";

import type { TreeProblem } from "../api/reportLayouts";
import { buildUser, withStatefulAuth } from "../testing/storybook-helpers";
import { buildBlockCatalogue, buildFieldCatalogue, buildWidgets } from "../testing/reportLayoutFixtures";
import { buildColourContext } from "../testing/reportLayoutFixtures";
import type { ColourEntry } from "../utils/reportColours";
import type { Tree } from "../utils/reportLayoutTree";
import { ReportLayoutSettings } from "./ReportLayoutSettings";

function Harness({
  problems = [], family = "document", initial = {}, organisation = false,
}: { problems?: TreeProblem[]; family?: "document" | "table"; initial?: Tree; organisation?: boolean }) {
  const [tree, setTree] = useState<Tree>({ schema_version: 1, family, nodes: [], ...initial });
  return (
    <>
      <ReportLayoutSettings
        tree={tree} onChange={setTree} family={family} blocks={buildBlockCatalogue()} problems={problems}
        env={{
          blocks: buildBlockCatalogue(), catalogue: buildFieldCatalogue(), widgets: buildWidgets(), variables: [], pageStyles: [], readOnly: false,
          colours: buildColourContext(), palette: (tree.palette ?? []) as ColourEntry[],
          ...(organisation ? { images: { library: { list: async () => [] } as never, scope: "organization" as const } } : {}),
        }}
      />
      <pre data-testid="tree" hidden>{JSON.stringify(tree)}</pre>
    </>
  );
}

/** The layout-level settings (page orientation, variables), shown in the block editor, and the problems that belong to no block. */
const meta: Meta<typeof Harness> = {
  title: "Components/ReportLayoutSettings", component: Harness, decorators: [withStatefulAuth(buildUser())],
};
export default meta;

type Story = StoryObj<typeof Harness>;

/** Opens a closed setting group by its bar (a group that is already open is left alone). */
const openGroup = async (canvas: ReturnType<typeof within>, name: string) => {
  const bar = canvas.getByRole("button", { name: `${name} section` });
  if (bar.getAttribute("aria-expanded") !== "true") await userEvent.click(bar);
};

export const OrientationIsSetOnTheTree: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Page orientation" }), "landscape");
    await waitFor(() => expect(JSON.parse(canvas.getByTestId("tree").textContent ?? "{}").orientation).toBe("landscape"));
  },
};

export const ATableLayoutHasNoOrientation: Story = {
  args: { family: "table" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await openGroup(canvas, "Variables and running");
    await expect(canvas.queryByRole("combobox", { name: "Page orientation" })).not.toBeInTheDocument();
    await expect(canvas.getByText("This layout has no variables.")).toBeInTheDocument();
  },
};

export const AProblemOnASettingShowsWithItAndOthersListAbove: Story = {
  args: { problems: [{ path: "variables[0].name", message: "Must be lower-case letters." }, { path: "family", message: "Wrong kind." }] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Must be lower-case letters.")).toBeVisible();
    await expect(canvas.getByText("family: Wrong kind.")).toBeInTheDocument();
  },
};

/** "Projects it runs for" is a choice on the layout, for either family. */
export const TheProjectsItRunsForAreSetOnTheTree: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await openGroup(canvas, "Variables and running");
    const choice = canvas.getByRole("combobox", { name: "Projects it runs for" });
    await expect(within(choice).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Not set (any number of projects)", "Any number of projects", "One project", "One project and its child projects",
    ]);
    await userEvent.selectOptions(choice, "one_and_children");
    await waitFor(() => expect(JSON.parse(canvas.getByTestId("tree").textContent ?? "{}").run_scope).toBe("one_and_children"));
  },
};

/** An organisation layout that prints the project's name suggests limiting it to one project, and the hint goes once it is. */
export const AnOrganisationLayoutPrintingTheProjectSuggestsSingleProject: Story = {
  args: { organisation: true, initial: { nodes: [{ type: "heading", text: "Sign-off for {{project_name}}" }] } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await openGroup(canvas, "Variables and running");
    await expect(canvas.getByRole("note")).toHaveTextContent("Projects it runs for");
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Projects it runs for" }), "one");
    await waitFor(() => expect(canvas.queryByRole("note")).not.toBeInTheDocument());
  },
};

export const AProjectLayoutGetsNoSingleProjectHint: Story = {
  args: { initial: { nodes: [{ type: "heading", text: "Sign-off for {{project_name}}" }] } },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("note")).not.toBeInTheDocument();
  },
};

/** The layout's colour scheme is a setting of the layout; a name a block uses cannot be removed from it. */
export const AColourSchemeIsASettingAndAUsedNameIsKept: Story = {
  args: {
    initial: {
      palette: [{ name: "plate", colour: "accent" }, { name: "ink", colour: "#102030" }],
      nodes: [{ type: "shape", shape: "rectangle", width: 3, height: 1, fill: "plate" }],
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await openGroup(canvas, "Look");
    await expect(canvas.getByRole("list", { name: "Colours in the scheme" })).toHaveTextContent("plate #0f62fe");
    await userEvent.click(canvas.getByRole("button", { name: "Remove colour plate" }));
    await expect(canvas.getByRole("alert")).toHaveTextContent("plate is used by a block");
    await userEvent.click(canvas.getByRole("button", { name: "Remove colour ink" }));
    await waitFor(() => expect(JSON.parse(canvas.getByTestId("tree").textContent ?? "{}").palette).toEqual([{ name: "plate", colour: "accent" }]));
  },
};

export const EmptyingTheSchemeRemovesTheKeyFromTheTree: Story = {
  args: { initial: { palette: [{ name: "ink", colour: "#102030" }] } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await openGroup(canvas, "Look");
    await userEvent.click(canvas.getByRole("button", { name: "Follow the organisation's colours" }));
    await waitFor(() => expect("palette" in JSON.parse(canvas.getByTestId("tree").textContent ?? "{}")).toBe(false));
  },
};

export const ATableLayoutHasNoColourScheme: Story = {
  args: { family: "table" },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByText("Colour scheme")).not.toBeInTheDocument();
  },
};

export const FontsAreSetOnTheTreeAndTheHeadingColourCanUseTheLayoutsScheme: Story = {
  args: { initial: { palette: [{ name: "plate", colour: "#0f62fe" }] } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await openGroup(canvas, "Look");
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Body font" }), "serif");
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Heading font" }), "mono");
    await userEvent.click(canvas.getByRole("button", { name: "Heading colour: Default (each format's own colour)" }));
    await userEvent.click(within(document.body).getByRole("button", { name: /^plate/ }));
    await waitFor(() => expect(JSON.parse(canvas.getByTestId("tree").textContent ?? "{}").styles).toEqual({
      body: { font: "serif" }, headings: { font: "mono", colour: "plate" },
    }));
  },
};

export const EmbedFontsIsAnOrdinarySwitchStoredOnlyWhenOn: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await openGroup(canvas, "Look");
    const box = canvas.getByRole("checkbox", { name: "Embed fonts" });
    await userEvent.click(box);
    await waitFor(() => expect(JSON.parse(canvas.getByTestId("tree").textContent ?? "{}").embed_fonts).toBe(true));
    await userEvent.click(box);
    await waitFor(() => expect("embed_fonts" in JSON.parse(canvas.getByTestId("tree").textContent ?? "{}")).toBe(false));
  },
};

export const ATableLayoutHasNoFonts: Story = {
  args: { family: "table" },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("combobox", { name: "Body font" })).not.toBeInTheDocument();
    await expect(within(canvasElement).queryByRole("checkbox", { name: "Embed fonts" })).not.toBeInTheDocument();
  },
};

/** The basic set and the header and footer are open; every other group is closed, and a closed group holding a setting says so. */
export const OnlyTheBasicSetStartsOpenAndClosedGroupsMarkWhatTheyHold: Story = {
  args: { initial: { embed_fonts: true, variables: [{ name: "kind", label: "Kind", type: "text" }], page_styles: [{ name: "Wide" }], margins: { top: 2 } } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("combobox", { name: "Page orientation" })).toBeVisible();
    await expect(canvas.getByRole("button", { name: "Header and footer section" })).toHaveAttribute("aria-expanded", "true");
    for (const [name, pill] of [["Look", "1 changed"], ["Variables and running", "1 changed"], ["Page styles", "1 page style"]]) {
      const bar = canvas.getByRole("button", { name: `${name} section` });
      await expect(bar).toHaveAttribute("aria-expanded", "false");
      await expect(bar).toHaveAccessibleDescription(pill);
    }
    await expect(canvas.getByRole("button", { name: "Tables section" })).not.toHaveAccessibleDescription(/changed/);
    await expect(canvas.queryByRole("checkbox", { name: "Embed fonts" })).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Look section" }));
    await expect(canvas.getByRole("checkbox", { name: "Embed fonts" })).toBeChecked();
  },
};

/** A closed group with a server problem inside opens itself, shows a danger pill and cannot be shut on the problem. */
export const AProblemHoldsItsGroupOpen: Story = {
  args: { problems: [{ path: "variables[0].name", message: "Must be lower-case letters." }] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const bar = canvas.getByRole("button", { name: "Variables and running section" });
    await expect(bar).toHaveAttribute("aria-expanded", "true");
    await expect(bar).toHaveAccessibleDescription("1 problem");
    await userEvent.click(bar);
    await expect(bar).toHaveAttribute("aria-expanded", "true");
    await expect(canvas.getByText("Must be lower-case letters.")).toBeVisible();
  },
};

/** A setting added to the server's catalogue that the table does not know still appears, under "Other settings". */
export const AnUnknownFieldIsNeverLost: Story = {
  render: () => {
    const blocks = buildBlockCatalogue();
    blocks.layout_fields = [...blocks.layout_fields, { ...blocks.layout_fields[0], key: "brand_new", label: "Brand new setting", kind: "boolean", default: false }];
    return (
      <ReportLayoutSettings
        tree={{ schema_version: 1, family: "document", nodes: [] }} onChange={() => {}} family="document" blocks={blocks} problems={[]}
        env={{ blocks, catalogue: buildFieldCatalogue(), widgets: buildWidgets(), variables: [], pageStyles: [], readOnly: false, colours: buildColourContext(), palette: [] }}
      />
    );
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Other settings section" }));
    await expect(canvas.getByRole("checkbox", { name: "Brand new setting" })).toBeVisible();
  },
};
