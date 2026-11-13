import type { Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter } from "react-router-dom";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { useTagFilter } from "../hooks/useTagFilter";
import { buildPlacementsApi, PLACEMENTS_PROJECT_ID } from "../testing/placementsFixtures";
import { ComponentFilterField } from "./ComponentFilterField";

function Harness({ api }: { api: React.ComponentProps<typeof ComponentFilterField>["api"] }) {
  const filter = useTagFilter();
  return (
    <div className="stack" style={{ maxWidth: 260 }}>
      <ComponentFilterField projectId={PLACEMENTS_PROJECT_ID} filter={filter} api={api} />
      <output aria-label="Query">{filter.query}</output>
    </div>
  );
}

/**
 * The component filter of a list's filter panel: tick components and categories; a record matches when it sits in any.
 * The list page sends `query` (or the list filters) with its list read.
 */
const meta: Meta<typeof Harness> = {
  title: "Components/ComponentFilterField",
  component: Harness,
  decorators: [(Story) => <MemoryRouter><Story /></MemoryRouter>],
};
export default meta;

type Story = StoryObj<typeof Harness>;

export const TickingComponentsAndCategoriesBuildsTheQuery: Story = {
  args: { api: buildPlacementsApi() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Component and category" }));
    await userEvent.click(await within(document.body).findByRole("checkbox", { name: "Software" }));
    await expect(canvas.getByLabelText("Query").textContent).toBe("component_id=c-sw");
    await userEvent.click(await within(document.body).findByRole("checkbox", { name: "Hardware / Power" }));
    await expect(canvas.getByLabelText("Query").textContent).toBe("component_id=c-sw&category_id=k-power");
  },
};

/** A project with no components shows no filter at all. */
export const HiddenWhenTheProjectHasNoComponents: Story = {
  args: { api: buildPlacementsApi(undefined, { tree: fn(async () => ({ components: [], categories: [] })) }) },
  play: async ({ canvasElement, args }) => {
    await waitFor(() => expect(args.api!.tree).toHaveBeenCalled());
    await expect(within(canvasElement).queryByText("Component and category")).not.toBeInTheDocument();
  },
};

/** The tree opens with every component expanded; a component's chevron hides and shows its categories. */
export const CollapsingAComponentHidesItsCategories: Story = {
  args: { api: buildPlacementsApi() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Component and category" }));
    const body = within(document.body);
    await expect(await body.findByRole("checkbox", { name: "Hardware / Power" })).toBeInTheDocument();
    await userEvent.click(body.getByRole("button", { name: "Collapse Hardware" }));
    await expect(body.queryByRole("checkbox", { name: "Hardware / Power" })).not.toBeInTheDocument();
    await userEvent.click(body.getByRole("button", { name: "Expand Hardware" }));
    await expect(await body.findByRole("checkbox", { name: "Hardware / Power" })).toBeInTheDocument();
  },
};

/** A search keeps the matching category and the component above it, and hides the rest. */
export const SearchKeepsTheComponentAboveAMatch: Story = {
  args: { api: buildPlacementsApi() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Component and category" }));
    const body = within(document.body);
    await userEvent.type(await body.findByRole("searchbox"), "Cool");
    await expect(await body.findByRole("checkbox", { name: "Hardware / Cooling" })).toBeInTheDocument();
    await expect(body.getByText("Hardware")).toBeInTheDocument();
    await expect(body.queryByRole("checkbox", { name: "Software" })).not.toBeInTheDocument();
    await expect(body.queryByRole("checkbox", { name: "Hardware / Power" })).not.toBeInTheDocument();
  },
};
