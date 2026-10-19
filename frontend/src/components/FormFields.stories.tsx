import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { CheckboxField, ColorField, DateField, FileField, TextAreaField, TextField, ToggleField } from "./FormFields";

const meta: Meta = { title: "Components/FormFields" };
export default meta;

type Story = StoryObj;

export const TextFieldIsLabelledAndReportsChanges: Story = {
  render: () => <TextField label="Role" value="" onChange={fn()} />,
  play: async ({ canvasElement }) => {
    await userEvent.type(within(canvasElement).getByLabelText("Role"), "x");
    await expect(within(canvasElement).getByText("Role")).toBeInTheDocument();
  },
};

export const TextFieldAriaLabelOverridesTheVisibleLabel: Story = {
  render: () => <TextField label="Name" ariaLabel="Persona name" value="Ada" onChange={fn()} />,
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByLabelText("Persona name")).toHaveValue("Ada");
  },
};

export const TextAreaShowsItsHint: Story = {
  render: () => <TextAreaField label="Contact" value="" onChange={fn()} hint="Confidential." rows={3} />,
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByLabelText("Contact")).toHaveAttribute("rows", "3");
    await expect(within(canvasElement).getByText("Confidential.")).toBeInTheDocument();
  },
};

export const DateFieldIsLabelledAndReportsChanges: Story = {
  render: () => <DateField label="Retain until" value="" onChange={fn()} hint="Optional." />,
  play: async ({ canvasElement }) => {
    const input = within(canvasElement).getByLabelText("Retain until");
    await expect(input).toHaveAttribute("type", "date");
    await expect(within(canvasElement).getByText("Optional.")).toBeInTheDocument();
  },
};

export const CheckboxFieldReportsToggles: Story = {
  render: () => {
    const onChange = fn();
    return <CheckboxField label="Consent recorded" checked={false} onChange={onChange} hint="Tick once agreed." />;
  },
  play: async ({ canvasElement }) => {
    const box = within(canvasElement).getByLabelText("Consent recorded");
    await expect(box).not.toBeChecked();
    await userEvent.click(box);
    await expect(within(canvasElement).getByText("Tick once agreed.")).toBeInTheDocument();
  },
};

export const TextFieldPassesExtraAttributesToTheInput: Story = {
  render: () => <TextField label="Port" value="25" onChange={fn()} inputProps={{ type: "number", min: 1, max: 65535 }} />,
  play: async ({ canvasElement }) => {
    const input = within(canvasElement).getByLabelText("Port");
    await expect(input).toHaveAttribute("type", "number");
    await expect(input).toHaveAttribute("max", "65535");
  },
};

export const FieldsCanBeDisabled: Story = {
  render: () => (
    <div>
      <TextField label="Display name" value="Ada" onChange={fn()} disabled hint="Managed by your organisation." />
      <CheckboxField label="Forced on" checked onChange={fn()} disabled title="Set by the organisation." />
    </div>
  ),
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByLabelText("Display name")).toBeDisabled();
    await expect(within(canvasElement).getByLabelText("Forced on")).toBeDisabled();
  },
};

export const AutoGrowTextAreaIsLabelled: Story = {
  render: () => <TextAreaField label="Description" value="" onChange={fn()} autoGrow />,
  play: async ({ canvasElement }) => {
    await userEvent.type(within(canvasElement).getByLabelText("Description"), "x");
    await expect(within(canvasElement).getByText("Description")).toBeInTheDocument();
  },
};

export const ColorFieldReportsChanges: Story = {
  render: () => <ColorField label="Accent colour" value="#336699" onChange={fn()} />,
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByLabelText("Accent colour")).toHaveValue("#336699");
  },
};

export const ToggleFieldNamesTheSwitchAndShowsItsHint: Story = {
  render: () => {
    const onChange = fn();
    return <ToggleField label="Require 2FA" checked={false} onChange={onChange} hint="Members must enrol before they can sign in." />;
  },
  play: async ({ canvasElement }) => {
    const toggle = within(canvasElement).getByRole("switch", { name: "Require 2FA" });
    await expect(toggle).toHaveAttribute("aria-checked", "false");
    await userEvent.click(toggle);
    await expect(within(canvasElement).getByText("Members must enrol before they can sign in.")).toBeInTheDocument();
  },
};

export const FileFieldReportsTheChosenFile: Story = {
  render: () => {
    const onChange = fn();
    return <FileField label="Import from a bundle" accept=".zip" onChange={onChange} hint="Optional." />;
  },
  play: async ({ canvasElement }) => {
    const input = within(canvasElement).getByLabelText("Import from a bundle");
    await expect(input).toHaveAttribute("type", "file");
    await userEvent.upload(input, new File(["x"], "bundle.zip", { type: "application/zip" }));
  },
};

export const DarkTheme: Story = { ...TextAreaShowsItsHint, globals: { theme: "dark" } };
