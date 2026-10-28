import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { ReportLayoutJsonField } from "./ReportLayoutJsonField";

function Harness({ initial }: { initial: unknown }) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <ReportLayoutJsonField label="Extra" value={value} onChange={setValue} />
      <pre data-testid="value" hidden>{JSON.stringify(value) ?? "undefined"}</pre>
      <button type="button" onClick={() => setValue({ replaced: true })}>Replace</button>
    </>
  );
}

/** A JSON box for a value the outline has no control for; the parent gets a value only while the text is valid. */
const meta: Meta<typeof Harness> = { title: "Components/ReportLayoutJsonField", component: Harness, args: { initial: { a: 1 } } };
export default meta;

type Story = StoryObj<typeof Harness>;

const valueOf = (el: HTMLElement) => within(el).getByTestId("value").textContent;

export const ValidJsonIsPassedOnAndInvalidIsHeldBack: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const box = canvas.getByRole("textbox", { name: "Extra (JSON)" });
    await userEvent.clear(box);
    await userEvent.type(box, '{{"b":');
    await expect(await canvas.findByRole("alert")).toHaveTextContent("This is not valid JSON.");
    // The last valid value is still the parent's.
    await expect(valueOf(canvasElement)).toBe("undefined");
    await userEvent.type(box, "2}");
    await waitFor(() => expect(valueOf(canvasElement)).toBe('{"b":2}'));
    await expect(canvas.queryByRole("alert")).not.toBeInTheDocument();
  },
};

export const ReplacingTheValueFromOutsideIsShown: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Replace" }));
    await waitFor(() => expect(canvas.getByRole("textbox", { name: "Extra (JSON)" })).toHaveValue(JSON.stringify({ replaced: true }, null, 2)));
  },
};
