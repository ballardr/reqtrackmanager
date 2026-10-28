import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { CommaListField } from "./CommaListField";

function Harness({ initial, parse }: { initial: unknown[]; parse?: (part: string) => unknown }) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <CommaListField label="Link types" value={value} onChange={setValue} parse={parse} />
      <pre data-testid="value" hidden>{JSON.stringify(value)}</pre>
      <button type="button" onClick={() => setValue(["replaced"])}>Replace</button>
    </>
  );
}

/** A short list typed separated by commas; the box keeps what is typed while the parent holds the parsed list. */
const meta: Meta<typeof Harness> = { title: "Components/CommaListField", component: Harness, args: { initial: [] } };
export default meta;

type Story = StoryObj<typeof Harness>;

const valueOf = (el: HTMLElement) => JSON.parse(within(el).getByTestId("value").textContent ?? "null");

export const TypingKeepsCommasAndSpacesWhileTheListIsParsed: Story = {
  play: async ({ canvasElement }) => {
    const box = within(canvasElement).getByRole("textbox", { name: "Link types" });
    await userEvent.type(box, "Causes, Blocks ,");
    await expect(box).toHaveValue("Causes, Blocks ,");
    await waitFor(() => expect(valueOf(canvasElement)).toEqual(["Causes", "Blocks"]));
  },
};

export const AListReplacedFromOutsideIsShown: Story = {
  args: { initial: ["a"] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("textbox", { name: "Link types" })).toHaveValue("a");
    await userEvent.click(canvas.getByRole("button", { name: "Replace" }));
    await expect(canvas.getByRole("textbox", { name: "Link types" })).toHaveValue("replaced");
  },
};

export const PartsCanBeParsedIntoNumbers: Story = {
  args: { initial: [], parse: (part: string) => Number(part) },
  play: async ({ canvasElement }) => {
    await userEvent.type(within(canvasElement).getByRole("textbox", { name: "Link types" }), "1, 2");
    await waitFor(() => expect(valueOf(canvasElement)).toEqual([1, 2]));
  },
};
