import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";

import type { TreeProblem } from "../api/reportLayouts";
import { buildBlockCatalogue, buildFieldCatalogue, buildWidgets } from "../testing/reportLayoutFixtures";
import type { Tree } from "../utils/reportLayoutTree";
import { ReportLayoutSettings } from "./ReportLayoutSettings";

function Harness({ problems = [], family = "document" }: { problems?: TreeProblem[]; family?: "document" | "table" }) {
  const [tree, setTree] = useState<Tree>({ schema_version: 1, family, nodes: [] });
  return (
    <>
      <ReportLayoutSettings
        tree={tree} onChange={setTree} family={family} blocks={buildBlockCatalogue()} problems={problems}
        env={{ blocks: buildBlockCatalogue(), catalogue: buildFieldCatalogue(), widgets: buildWidgets(), variables: [], pageStyles: [], readOnly: false }}
      />
      <pre data-testid="tree" hidden>{JSON.stringify(tree)}</pre>
    </>
  );
}

/** The layout-level settings (page orientation, variables) and the problems that belong to no block. */
const meta: Meta<typeof Harness> = { title: "Components/ReportLayoutSettings", component: Harness };
export default meta;

type Story = StoryObj<typeof Harness>;

export const OrientationIsSetOnTheTree: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByText("Layout settings"));
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Page orientation" }), "landscape");
    await waitFor(() => expect(JSON.parse(canvas.getByTestId("tree").textContent ?? "{}").orientation).toBe("landscape"));
  },
};

export const ATableLayoutHasNoOrientation: Story = {
  args: { family: "table" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByText("Layout settings"));
    await expect(canvas.queryByRole("combobox", { name: "Page orientation" })).not.toBeInTheDocument();
    await expect(canvas.getByText("This layout has no variables.")).toBeInTheDocument();
  },
};

export const AProblemOnASettingOpensTheSectionAndOthersListAbove: Story = {
  args: { problems: [{ path: "variables[0].name", message: "Must be lower-case letters." }, { path: "family", message: "Wrong kind." }] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Must be lower-case letters.")).toBeVisible();
    await expect(canvas.getByText("family: Wrong kind.")).toBeInTheDocument();
  },
};
