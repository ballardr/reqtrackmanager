import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { useTextSelections } from "../hooks/useTextSelections";
import { MarkButtons } from "./MarkButtons";

function Harness({ disabled }: { disabled?: boolean }) {
  const [text, setText] = useState("Draft copy");
  const { remember, mark } = useTextSelections<"words">();
  return (
    <div>
      <input aria-label="Words" value={text} onChange={(e) => setText(e.target.value)} onSelect={remember("words")} onBlur={remember("words")} />
      <MarkButtons nameOf={(name) => `Words: ${name}`} disabled={disabled} onMark={(marker) => mark("words", text, marker, setText)} />
    </div>
  );
}

/** Bold and Italic beside a text that reads `**` and `*` marks; a press wraps the words selected in it. */
const meta: Meta<typeof Harness> = { title: "Components/MarkButtons", component: Harness };
export default meta;

type Story = StoryObj<typeof Harness>;

export const BoldAndItalicWrapTheSelectedWords: Story = {
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    const input = view.getByRole("textbox", { name: "Words" }) as HTMLInputElement;
    input.focus();
    input.setSelectionRange(0, 5);
    await userEvent.click(view.getByRole("button", { name: "Words: Bold" }));
    await waitFor(() => expect(input).toHaveValue("**Draft** copy"));
    // The selection is put back on the wrapped words on the next frame.
    await waitFor(() => expect(input.selectionStart).toBe(2));
    await expect(input.selectionEnd).toBe(7);
  },
};

export const WithNothingSelectedTheWholeTextIsMarked: Story = {
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    const input = view.getByRole("textbox", { name: "Words" }) as HTMLInputElement;
    input.focus();
    input.setSelectionRange(4, 4);
    await userEvent.click(view.getByRole("button", { name: "Words: Italic" }));
    await waitFor(() => expect(input).toHaveValue("*Draft copy*"));
  },
};

export const DisabledButtonsDoNothing: Story = {
  args: { disabled: true },
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    await expect(view.getByRole("button", { name: "Words: Bold" })).toBeDisabled();
    await expect(view.getByRole("button", { name: "Words: Italic" })).toBeDisabled();
  },
};
