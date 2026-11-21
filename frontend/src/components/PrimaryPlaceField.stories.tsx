import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import type { PlacementPair } from "../api/placements";
import { buildTree } from "../testing/placementsFixtures";
import { requiredCaptions } from "../testing/requiredMarkers";
import { PrimaryPlaceField } from "./PrimaryPlaceField";

function Host({ categoryId = "" }: { categoryId?: string }) {
  const [place, setPlace] = useState<PlacementPair | null>(categoryId ? { component_id: "c-hw", category_id: categoryId } : null);
  return (
    <div style={{ maxWidth: 320 }}>
      <PrimaryPlaceField tree={buildTree()} categoryId={place?.category_id ?? ""} help="The component and category." onChange={setPlace} />
      <output aria-label="Chosen">{place ? `${place.component_id}/${place.category_id}` : "none"}</output>
    </div>
  );
}

/**
 * The one component and category a requirement belongs to, chosen together from the project's tree: each component is a
 * heading and a category is the choice, so the pair cannot disagree.
 */
const meta: Meta<typeof Host> = { title: "Components/PrimaryPlaceField", component: Host };
export default meta;

type Story = StoryObj<typeof Host>;

export const IsRequired: Story = {
  play: async ({ canvasElement }) => {
    await expect(requiredCaptions(canvasElement)).toEqual(["Component and category"]);
  },
};

/** Choosing a category chooses its component with it, and closes the list. */
export const ChoosingACategoryChoosesThePair: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Component and category" }));
    const list = within(document.body);
    await userEvent.click(await list.findByRole("radio", { name: "Hardware / Power" }));
    await expect(canvas.getByLabelText("Chosen").textContent).toBe("c-hw/k-power");
    await expect(canvas.getByRole("button", { name: "Component and category" })).toHaveTextContent("Hardware / Power");
    await expect(list.queryByRole("radio", { name: "Hardware / Cooling" })).not.toBeInTheDocument();
  },
};

/** A component is a heading only: it cannot be chosen on its own. */
export const AComponentCannotBeChosenAlone: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Component and category" }));
    await expect(await within(document.body).findByRole("radio", { name: "Hardware" })).toBeDisabled();
  },
};

/** The search keeps a matching category with its component above it. */
export const SearchNarrowsToAMatch: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Component and category" }));
    const list = within(document.body);
    await userEvent.type(await list.findByRole("searchbox"), "Cool");
    await expect(await list.findByRole("radio", { name: "Hardware / Cooling" })).toBeInTheDocument();
    await expect(list.queryByRole("radio", { name: "Hardware / Power" })).not.toBeInTheDocument();
  },
};

/** The current choice shows on the trigger. */
export const ShowsTheCurrentChoice: Story = {
  args: { categoryId: "k-cool" },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("button", { name: "Component and category" })).toHaveTextContent("Hardware / Cooling");
  },
};
