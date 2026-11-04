import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, fn, userEvent, within } from "storybook/test";

import { JsonObjectField } from "./JsonObjectField";

/** A small JSON object box: parses as you type, reports validity and hands the parent the object only while it is valid. */
const meta: Meta<typeof JsonObjectField> = {
  title: "Components/Reports/JsonObjectField",
  component: JsonObjectField,
};
export default meta;

type Story = StoryObj<typeof JsonObjectField>;

function Harness({ onChange, onValidity }: { onChange: (v: Record<string, unknown> | undefined) => void; onValidity: (ok: boolean) => void }) {
  const [value, setValue] = useState<Record<string, unknown> | undefined>({ categories: ["Security"] });
  return (
    <JsonObjectField
      label="Fixed values (JSON)" help="Values this report always uses." value={value}
      onChange={(next) => { setValue(next); onChange(next); }} onValidity={onValidity}
    />
  );
}

export const ShowsTheValueAsJson: Story = {
  render: () => <Harness onChange={fn()} onValidity={fn()} />,
  play: async ({ canvasElement }) => {
    const box = (await within(canvasElement).findByRole("textbox", { name: "Fixed values (JSON)" })) as HTMLTextAreaElement;
    await expect(box.value).toBe('{"categories":["Security"]}');
  },
};

export const AValidObjectIsHandedOverAndAnInvalidOneIsFlagged: Story = {
  render: () => <Harness onChange={fn()} onValidity={fn()} />,
  play: async ({ canvasElement }) => {
    const box = await within(canvasElement).findByRole("textbox", { name: "Fixed values (JSON)" });
    await userEvent.clear(box);
    await userEvent.type(box, "{{\"a\": 1");
    await expect(await within(canvasElement).findByRole("alert")).toHaveTextContent("This is not valid JSON.");
    await userEvent.type(box, "}");
    await expect(within(canvasElement).queryByRole("alert")).not.toBeInTheDocument();
  },
};

export const AnArrayIsNotAnObject: Story = {
  render: () => <Harness onChange={fn()} onValidity={fn()} />,
  play: async ({ canvasElement }) => {
    const box = await within(canvasElement).findByRole("textbox", { name: "Fixed values (JSON)" });
    await userEvent.clear(box);
    await userEvent.type(box, "[[1, 2]");
    await expect(await within(canvasElement).findByRole("alert")).toHaveTextContent("This must be a JSON object.");
  },
};

export const EmptyMeansNone: Story = {
  render: () => {
    const onChange = fn();
    return <Harness onChange={onChange} onValidity={fn()} />;
  },
  play: async ({ canvasElement }) => {
    const box = await within(canvasElement).findByRole("textbox", { name: "Fixed values (JSON)" });
    await userEvent.clear(box);
    await expect(within(canvasElement).queryByRole("alert")).not.toBeInTheDocument();
  },
};
