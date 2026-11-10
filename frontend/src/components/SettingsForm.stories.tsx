import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import { ToastProvider } from "../context/ToastContext";
import { TextField } from "./FormFields";
import { SettingsForm } from "./SettingsForm";

const meta: Meta<typeof SettingsForm> = {
  title: "Components/SettingsForm",
  component: SettingsForm,
  decorators: [(Story) => <ToastProvider><Story /></ToastProvider>],
};
export default meta;

type Story = StoryObj<typeof SettingsForm>;

function Harness({ fail }: { fail?: boolean }) {
  const [saved, setSaved] = useState("Original");
  const [value, setValue] = useState("Original");
  return (
    <SettingsForm
      dirty={value !== saved}
      successMessage="Settings saved."
      onSave={async () => {
        if (fail) throw new Error("The server refused the change.");
        setSaved(value);
      }}
    >
      <TextField helpNotNeeded label="Title" value={value} onChange={setValue} />
    </SettingsForm>
  );
}

/** Save is unavailable until a field changes, then saves and confirms with a toast. */
export const SaveAfterChange: Story = {
  render: () => <Harness />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const save = canvas.getByRole("button", { name: "Save" });
    await expect(save).toBeDisabled();
    await userEvent.type(canvas.getByLabelText("Title"), " edited");
    await expect(save).toBeEnabled();
    await userEvent.click(save);
    await expect(await within(document.body).findByText("Settings saved.")).toBeInTheDocument();
    await expect(save).toBeDisabled();
  },
};

/** A failure is drawn beside Save and the fields keep their edits. */
export const FailureStaysBesideSave: Story = {
  render: () => <Harness fail />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByLabelText("Title"), " edited");
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));
    await expect(await canvas.findByRole("alert")).toHaveTextContent("The server refused the change.");
    await expect(canvas.getByLabelText("Title")).toHaveValue("Original edited");
  },
};
