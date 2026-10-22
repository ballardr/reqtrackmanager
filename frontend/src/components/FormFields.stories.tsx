import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { requiredCaptions } from "../testing/requiredMarkers";
import { CheckboxField, ColorField, DateField, FileField, InlineTextInput, TextAreaField, TextField, ToggleField } from "./FormFields";

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

const LONG_LABEL = "Hide intentional limitations that the team has agreed to live with";

/** The first line of the label's text sits beside the box, whatever the container's width. */
async function expectBoxBesideItsText(canvasElement: HTMLElement) {
  const box = within(canvasElement).getByRole("checkbox");
  const text = box.parentElement!;
  const range = document.createRange();
  range.setStart(text.lastChild!, 0);
  range.setEnd(text.lastChild!, 1);
  const first = range.getClientRects()[0];
  const b = box.getBoundingClientRect();
  // The box and the first character of the text overlap vertically, and the text starts to the right of the box.
  await expect(first.left).toBeGreaterThanOrEqual(b.right - 1);
  await expect(Math.abs((first.top + first.height / 2) - (b.top + b.height / 2))).toBeLessThan(first.height);
}

/** A label long enough to wrap in a narrow container hangs beside its box, never under it. */
export const CheckboxLongLabelWrapsBesideTheBox: Story = {
  render: () => <div style={{ width: 220 }}><CheckboxField label={LONG_LABEL} checked={false} onChange={fn()} helpNotNeeded /></div>,
  play: async ({ canvasElement }) => {
    await expectBoxBesideItsText(canvasElement);
    const label = within(canvasElement).getByRole("checkbox").parentElement!;
    // More than one line of text, yet the box is still level with the first.
    await expect(label.getBoundingClientRect().height).toBeGreaterThan(30);
  },
};

export const CheckboxLongLabelWithHelpAndHint: Story = {
  render: () => (
    <div style={{ width: 220 }}>
      <CheckboxField label={LONG_LABEL} checked={false} onChange={fn()} help="Hides pain points marked as intentional." hint="Shown again when unticked." />
    </div>
  ),
  play: async ({ canvasElement }) => {
    await expectBoxBesideItsText(canvasElement);
    await expect(within(canvasElement).getByText("Shown again when unticked.")).toBeInTheDocument();
  },
};

export const CheckboxShortLabelStaysOnOneLine: Story = {
  render: () => <CheckboxField label="Include archived" checked={false} onChange={fn()} helpNotNeeded />,
  play: async ({ canvasElement }) => {
    await expectBoxBesideItsText(canvasElement);
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

/** A caption-less input in an inline row is named by its `ariaLabel`, and reports changes. */
export const InlineTextInputIsNamedByItsAriaLabel: Story = {
  render: () => <InlineTextInput ariaLabel="Name: Alpha" value="Alpha" onChange={fn()} maxWidth={220} />,
  play: async ({ canvasElement }) => {
    const input = within(canvasElement).getByLabelText("Name: Alpha");
    await expect(input).toHaveValue("Alpha");
    await expect(input).toHaveStyle({ maxWidth: "220px" });
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

/** The wheel, the hex box and the presets stay in step; `#rgb` is widened, and a non-colour is flagged and never reported. */
export const ColorFieldHexPresetsAndNoColour: Story = {
  render: () => {
    const onChange = fn();
    return (
      <ColorField
        helpNotNeeded label="Tag colour" value="" onChange={onChange}
        presets={[{ name: "Blue", hex: "#2b6cb0" }, { name: "Red", hex: "#c53030" }]} emptyLabel="No colour"
      />
    );
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const hex = canvas.getByRole("textbox", { name: "Tag colour (hex code)" });
    await userEvent.type(hex, "0a8");
    await expect(hex).not.toHaveAttribute("aria-invalid");
    await userEvent.clear(hex);
    await userEvent.type(hex, "nope");
    await expect(hex).toHaveAttribute("aria-invalid", "true");
    await expect(canvas.getByRole("alert")).toHaveTextContent("Enter a colour as #rgb or #rrggbb.");
    await expect(canvas.getByRole("button", { name: "No colour" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(canvas.getByRole("button", { name: "Blue" }));
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

/** `required` puts a `*` after the caption (hidden from assistive technology) and the constraint on the control. */
export const RequiredFieldsAreStarredAndConstrained: Story = {
  render: () => (
    <div className="stack">
      <TextField helpNotNeeded required label="Title" value="" onChange={fn()} />
      <TextAreaField helpNotNeeded required label="Statement" value="" onChange={fn()} />
      <DateField helpNotNeeded required label="Due" value="" onChange={fn()} />
      <TextField helpNotNeeded label="Notes" value="" onChange={fn()} />
    </div>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(requiredCaptions(canvasElement)).toEqual(["Title", "Statement", "Due"]);
    for (const name of ["Title", "Statement", "Due"]) {
      const control = canvas.getByLabelText(name);
      await expect(control).toBeRequired();
      await expect(control).toHaveAttribute("aria-required", "true");
    }
    await expect(canvas.getByLabelText("Notes")).not.toBeRequired();
    // The star is decoration for sighted users: the accessible name stays the bare caption.
    await expect(canvasElement.querySelector(".field-required")).toHaveAttribute("aria-hidden", "true");
  },
};
