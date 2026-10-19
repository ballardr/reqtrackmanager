import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { CheckboxField, DateField, TextAreaField, TextField, ToggleField } from "./FormFields";
import { FormGrid } from "./FormGrid";
import { LabeledSelect } from "./LabeledSelect";
import { Modal } from "./Modal";
import { RecordFieldGroup } from "./RecordDetailParts";

const HELP = "How much this persona counts when scores are rolled up across personas. A positive number; leave blank to weight every persona equally.";

const meta: Meta = { title: "Components/FieldHelp" };
export default meta;

type Story = StoryObj;

/** Opens the field's help with the mouse, reads it, then closes it with the same button. */
export const OpensAndClosesByMouse: Story = {
  render: () => <TextField label="Importance weight" help={HELP} value="" onChange={fn()} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const button = canvas.getByRole("button", { name: "Help: Importance weight" });
    await expect(button).toHaveAttribute("aria-expanded", "false");
    await expect(canvas.queryByText(HELP)).not.toBeInTheDocument();

    await userEvent.click(button);
    await expect(canvas.getByText(HELP)).toBeVisible();
    await expect(button).toHaveAttribute("aria-expanded", "true");

    await userEvent.click(button);
    await expect(canvas.queryByText(HELP)).not.toBeInTheDocument();
  },
};

/** The button is reached by Tab, opened by Enter and dismissed by Escape, leaving focus on the button. */
export const OpensAndClosesByKeyboard: Story = {
  render: () => <TextField label="Importance weight" help={HELP} value="" onChange={fn()} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const button = canvas.getByRole("button", { name: "Help: Importance weight" });
    button.focus();
    await userEvent.keyboard("{Enter}");
    await expect(canvas.getByText(HELP)).toBeVisible();
    await userEvent.keyboard("{Escape}");
    await expect(canvas.queryByText(HELP)).not.toBeInTheDocument();
    await expect(button).toHaveFocus();
  },
};

/** Pressing the help button does not focus or change the field it describes. */
export const OpeningHelpDoesNotTouchTheField: Story = {
  render: () => {
    const onChange = fn();
    return <TextField label="Importance weight" help={HELP} value="3" onChange={onChange} />;
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Help: Importance weight" }));
    await expect(canvas.getByLabelText("Importance weight")).not.toHaveFocus();
    await expect(canvas.getByLabelText("Importance weight")).toHaveValue("3");
  },
};

/** A field with no `help` renders the plain caption and no button. */
export const NoHelpMeansNoButton: Story = {
  render: () => <TextField label="Title" helpNotNeeded value="" onChange={fn()} />,
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("button")).not.toBeInTheDocument();
  },
};

/** Every shared field component shows the same button after its caption. */
export const EveryFieldComponentCarriesHelp: Story = {
  render: () => (
    <FormGrid minColumn="16rem">
      <TextField label="Text" help="Text help." value="" onChange={fn()} />
      <TextAreaField label="Long text" help="Long text help." value="" onChange={fn()} />
      <DateField label="Date" help="Date help." value="" onChange={fn()} />
      <LabeledSelect label="Choice" help="Choice help." value="" onChange={fn()} options={[{ value: "a", label: "A" }]} />
      <CheckboxField label="Tick me" heading="Heading" help="Checkbox heading help." checked={false} onChange={fn()} />
      <CheckboxField label="Plain checkbox" help="Plain checkbox help." checked={false} onChange={fn()} />
      <ToggleField label="Switch" help="Switch help." checked={false} onChange={fn()} />
      <RecordFieldGroup label="Group" help="Group help."><span>value</span></RecordFieldGroup>
    </FormGrid>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    for (const label of ["Text", "Long text", "Date", "Choice", "Heading", "Plain checkbox", "Switch", "Group"]) {
      await userEvent.click(canvas.getByRole("button", { name: `Help: ${label}` }));
    }
    for (const text of ["Text help.", "Long text help.", "Date help.", "Choice help.", "Checkbox heading help.", "Plain checkbox help.", "Switch help.", "Group help."]) {
      await expect(canvas.getByText(text)).toBeVisible();
    }
  },
};

/** A long help text wraps under the caption inside a narrow column and never overflows it. */
export const LongTextInANarrowColumn: Story = {
  render: () => (
    <div data-testid="column" style={{ width: 220 }}>
      <TextField label="Importance weight" help={`${HELP} ${HELP}`} value="" onChange={fn()} />
    </div>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Help: Importance weight" }));
    const note = canvas.getByRole("note");
    await expect(note.getBoundingClientRect().right).toBeLessThanOrEqual(canvas.getByTestId("column").getBoundingClientRect().right + 1);
  },
};

/** In a dialog, Escape closes the help first and leaves the dialog open. */
export const EscapeClosesHelpBeforeTheDialog: Story = {
  render: () => (
    <Modal title="Edit persona" onClose={fn()}>
      <TextField label="Importance weight" help={HELP} value="" onChange={fn()} />
    </Modal>
  ),
  play: async () => {
    const body = within(document.body);
    const button = body.getByRole("button", { name: "Help: Importance weight" });
    button.focus();
    await userEvent.keyboard("{Enter}");
    await expect(body.getByText(HELP)).toBeVisible();
    await userEvent.keyboard("{Escape}");
    await expect(body.queryByText(HELP)).not.toBeInTheDocument();
  },
};
