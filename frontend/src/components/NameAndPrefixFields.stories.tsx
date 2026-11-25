import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";

import type { NodeValues } from "../api/structure";
import { buildStructureApi, STRUCTURE_PROJECT_ID } from "../testing/structureFixtures";
import { requiredCaptions } from "../testing/requiredMarkers";
import { NameAndPrefixFields } from "./NameAndPrefixFields";

function Host({ initial = { name: "", prefix: "" }, followName = true, kind = "component" as const, componentId }: {
  initial?: NodeValues; followName?: boolean; kind?: "component" | "category"; componentId?: string;
}) {
  const [values, setValues] = useState(initial);
  return (
    <div className="stack" style={{ maxWidth: 360 }}>
      <NameAndPrefixFields
        api={buildStructureApi()} projectId={STRUCTURE_PROJECT_ID} kind={kind} componentId={componentId}
        followName={followName} value={values} onChange={setValues}
      />
    </div>
  );
}

/**
 * The name and prefix of a component or category. The prefix is suggested from the name by the server and follows it
 * until the person types one; a typed prefix is never overwritten.
 */
const meta: Meta<typeof Host> = { title: "Components/NameAndPrefixFields", component: Host };
export default meta;

type Story = StoryObj<typeof Host>;

export const RequiredFieldsAreMarked: Story = {
  play: async ({ canvasElement }) => {
    await expect(requiredCaptions(canvasElement)).toEqual(["Name", "Prefix"]);
  },
};

export const PrefixFollowsTheName: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const name = canvas.getByRole("textbox", { name: "Name" });
    await userEvent.type(name, "Power Supply");
    await waitFor(() => expect(canvas.getByRole("textbox", { name: "Prefix" })).toHaveValue("PS"));
    await userEvent.clear(name);
    await userEvent.type(name, "Thermal");
    await waitFor(() => expect(canvas.getByRole("textbox", { name: "Prefix" })).toHaveValue("THERMA"));
  },
};

/** A prefix the person typed stays, whatever the name becomes. */
export const ATypedPrefixIsNeverOverwritten: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByRole("textbox", { name: "Name" }), "Power Supply");
    const prefix = canvas.getByRole("textbox", { name: "Prefix" });
    await waitFor(() => expect(prefix).toHaveValue("PS"));
    await userEvent.type(prefix, "x");
    await expect(prefix).toHaveValue("PSX");
    await userEvent.type(canvas.getByRole("textbox", { name: "Name" }), " Unit");
    await new Promise((resolve) => setTimeout(resolve, 600));
    await expect(prefix).toHaveValue("PSX");
  },
};

/** Clearing the prefix hands it back to the suggestion. */
export const ClearingThePrefixResumesTheSuggestion: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByRole("textbox", { name: "Name" }), "Power Supply");
    const prefix = canvas.getByRole("textbox", { name: "Prefix" });
    await waitFor(() => expect(prefix).toHaveValue("PS"));
    await userEvent.clear(prefix);
    await waitFor(() => expect(prefix).toHaveValue("PS"));
  },
};

/** A prefix in use among the siblings is numbered; a name with no letter leaves the field empty. */
export const ACollisionIsNumberedAndANameWithNoLetterLeavesItEmpty: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByRole("textbox", { name: "Name" }), "Hard");
    await waitFor(() => expect(canvas.getByRole("textbox", { name: "Prefix" })).toHaveValue("HARD"));
    await userEvent.clear(canvas.getByRole("textbox", { name: "Name" }));
    await userEvent.type(canvas.getByRole("textbox", { name: "Name" }), "Hardware Wiring");
    await waitFor(() => expect(canvas.getByRole("textbox", { name: "Prefix" })).toHaveValue("HW2"));
    await userEvent.clear(canvas.getByRole("textbox", { name: "Name" }));
    await userEvent.type(canvas.getByRole("textbox", { name: "Name" }), "###");
    await waitFor(() => expect(canvas.getByRole("textbox", { name: "Prefix" })).toHaveValue(""));
  },
};

/** An edit starts with the stored prefix and keeps it when the name changes. */
export const AnEditKeepsTheStoredPrefix: Story = {
  args: { initial: { name: "Hardware", prefix: "HW" }, followName: false },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByRole("textbox", { name: "Name" }), " v2");
    await new Promise((resolve) => setTimeout(resolve, 600));
    await expect(canvas.getByRole("textbox", { name: "Prefix" })).toHaveValue("HW");
  },
};

/** Categories are numbered among their own component's categories. */
export const CategoryPrefixesAreNumberedWithinTheirComponent: Story = {
  args: { kind: "category", componentId: "c-hw" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByRole("textbox", { name: "Name" }), "Cooling");
    await waitFor(() => expect(canvas.getByRole("textbox", { name: "Prefix" })).toHaveValue("COOLIN"));
    await userEvent.clear(canvas.getByRole("textbox", { name: "Name" }));
    await userEvent.type(canvas.getByRole("textbox", { name: "Name" }), "Power");
    await waitFor(() => expect(canvas.getByRole("textbox", { name: "Prefix" })).toHaveValue("POWER"));
  },
};
