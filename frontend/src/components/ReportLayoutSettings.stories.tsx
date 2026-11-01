import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";

import type { TreeProblem } from "../api/reportLayouts";
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
const meta: Meta<typeof Harness> = { title: "Components/ReportLayoutSettings", component: Harness };
export default meta;

type Story = StoryObj<typeof Harness>;

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
