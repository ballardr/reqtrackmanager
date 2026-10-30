import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { TextListField } from "./TextListField";

function Host({ initial = [], disabled = false }: { initial?: string[]; disabled?: boolean }) {
  const [list, setList] = useState(initial);
  return (
    <>
      <TextListField label="File names" value={list} onChange={setList} hint="One per line." help="Patterns, one per line." disabled={disabled} />
      <output aria-label="List">{JSON.stringify(list)}</output>
    </>
  );
}

/** A list edited as one entry per line: blanks and surrounding spaces are dropped from the reported list. */
const meta: Meta<typeof Host> = { title: "Components/TextListField", component: Host };
export default meta;

type Story = StoryObj<typeof Host>;

export const EachLineIsOneEntryAndBlanksAreDropped: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByRole("textbox", { name: "File names" }), "  a.png  {enter}{enter}b*");
    await waitFor(() => expect(canvas.getByLabelText("List")).toHaveTextContent('["a.png","b*"]'));
    await expect(canvas.getByRole("textbox", { name: "File names" })).toHaveValue("  a.png  \n\nb*");
  },
};

export const AnExistingListIsShownOnePerLine: Story = {
  args: { initial: ["site-*", "plan.png"] },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("textbox", { name: "File names" })).toHaveValue("site-*\nplan.png");
  },
};

export const ReadOnlyDisablesTheBox: Story = {
  args: { initial: ["a"], disabled: true },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("textbox", { name: "File names" })).toBeDisabled();
  },
};
