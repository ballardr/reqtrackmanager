import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { CheckboxField, DateField, TextAreaField, TextField, ToggleField } from "./FormFields";
import { FormGrid } from "./FormGrid";
import { LabeledSelect } from "./LabeledSelect";
import { Modal } from "./Modal";
import { RecordFieldGroup } from "./RecordDetailParts";
import { SidePanel } from "./SidePanel";

const HELP = "How much this persona counts when scores are rolled up across personas. A positive number; leave blank to weight every persona equally.";

const meta: Meta = { title: "Components/FieldHelp" };
export default meta;

type Story = StoryObj;

const body = () => within(document.body);
/** The tooltip is portalled to `document.body`, so it is found there and never inside the canvas. */
const tip = () => body().queryByRole("tooltip", { hidden: true });

/** Click pins the help open, a second click closes it; hovering alone shows it without pinning. */
export const OpensAndClosesByMouse: Story = {
  render: () => <TextField label="Importance weight" help={HELP} value="" onChange={fn()} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const button = canvas.getByRole("button", { name: "Help: Importance weight" });
    await expect(tip()).not.toBeInTheDocument();

    await userEvent.hover(button);
    await expect(await body().findByRole("tooltip", { hidden: true })).toHaveTextContent(HELP);
    await userEvent.unhover(button);
    await waitFor(() => expect(tip()).not.toBeInTheDocument());

    await userEvent.click(button);
    await expect(await body().findByRole("tooltip", { hidden: true })).toHaveTextContent(HELP);
    await userEvent.unhover(button);
    await expect(tip()).toBeInTheDocument(); // pinned: moving away does not close it

    await userEvent.click(button);
    await waitFor(() => expect(tip()).not.toBeInTheDocument());
  },
};

/** The button is reached by Tab (which shows the help), pinned by Enter and dismissed by Escape, leaving focus on the button. */
export const OpensAndClosesByKeyboard: Story = {
  render: () => <TextField label="Importance weight" help={HELP} value="" onChange={fn()} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const button = canvas.getByRole("button", { name: "Help: Importance weight" });
    button.focus();
    await expect(await body().findByRole("tooltip", { hidden: true })).toHaveTextContent(HELP);
    await expect(button).toHaveAccessibleDescription(HELP);
    await userEvent.keyboard("{Enter}");
    await expect(tip()).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(tip()).not.toBeInTheDocument());
    await expect(button).toHaveFocus();
  },
};

/** A press anywhere outside the button closes a pinned help. */
export const OutsidePressCloses: Story = {
  render: () => (
    <div>
      <TextField label="Importance weight" help={HELP} value="" onChange={fn()} />
      <p>Elsewhere on the page</p>
    </div>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Help: Importance weight" }));
    await expect(await body().findByRole("tooltip", { hidden: true })).toBeInTheDocument();
    await userEvent.click(canvas.getByText("Elsewhere on the page"));
    await waitFor(() => expect(tip()).not.toBeInTheDocument());
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

/** Opening the help moves nothing: the field below the caption keeps its exact position and size. */
export const OpeningHelpDoesNotShiftTheLayout: Story = {
  render: () => (
    <FormGrid minColumn="16rem">
      <TextField label="Importance weight" help={HELP} value="" onChange={fn()} />
    </FormGrid>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const field = canvas.getByLabelText("Importance weight");
    const before = field.getBoundingClientRect();
    await userEvent.click(canvas.getByRole("button", { name: "Help: Importance weight" }));
    await expect(await body().findByRole("tooltip", { hidden: true })).toBeInTheDocument();
    const after = field.getBoundingClientRect();
    await expect([after.top, after.left, after.width, after.height]).toEqual([before.top, before.left, before.width, before.height]);
  },
};

/** A field with no `help` renders the plain caption and no button. */
export const NoHelpMeansNoButton: Story = {
  render: () => <TextField label="Title" helpNotNeeded value="" onChange={fn()} />,
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("button")).not.toBeInTheDocument();
  },
};

/** Every shared field component shows the same button after its caption, and each opens its own text. */
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
    const pairs: [string, string][] = [
      ["Text", "Text help."], ["Long text", "Long text help."], ["Date", "Date help."], ["Choice", "Choice help."],
      ["Heading", "Checkbox heading help."], ["Plain checkbox", "Plain checkbox help."], ["Switch", "Switch help."], ["Group", "Group help."],
    ];
    for (const [label, text] of pairs) {
      const button = canvas.getByRole("button", { name: `Help: ${label}` });
      await userEvent.click(button);
      await expect(await body().findByRole("tooltip", { hidden: true })).toHaveTextContent(text);
      await userEvent.click(button);
      await waitFor(() => expect(tip()).not.toBeInTheDocument());
    }
  },
};

/** A long help text wraps inside a bounded bubble that stays on screen, even from a narrow column. */
export const LongTextInANarrowColumn: Story = {
  render: () => (
    <div data-testid="column" style={{ width: 220 }}>
      <TextField label="Importance weight" help={`${HELP} ${HELP}`} value="" onChange={fn()} />
    </div>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Help: Importance weight" }));
    const bubble = await body().findByRole("tooltip", { hidden: true });
    await waitFor(() => expect(bubble).toHaveStyle({ opacity: "1" }));
    const rect = bubble.getBoundingClientRect();
    await expect(rect.left).toBeGreaterThanOrEqual(7);
    await expect(rect.right).toBeLessThanOrEqual(window.innerWidth - 7);
    await expect(rect.width).toBeLessThanOrEqual(22 * 16 + 1); // wrapped, not one long line
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
    const button = body().getByRole("button", { name: "Help: Importance weight" });
    button.focus();
    await userEvent.keyboard("{Enter}");
    await expect(await body().findByRole("tooltip", { hidden: true })).toHaveTextContent(HELP);
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(tip()).not.toBeInTheDocument());
    await expect(body().getByRole("dialog")).toBeVisible();
  },
};

/** The z-index of the fixed overlay that contains `element` (a dialog's backdrop or a panel's root). */
function overlayZIndex(element: HTMLElement): number {
  for (let node: HTMLElement | null = element; node; node = node.parentElement) {
    const style = getComputedStyle(node);
    if (style.position === "fixed" && style.zIndex !== "auto") return Number(style.zIndex);
  }
  throw new Error("No fixed overlay around the dialog.");
}

/** Help opened inside a dialog or side panel is drawn above it, never behind it (the bubble's layer is above both overlays). */
export const HelpShowsAboveAModalAndASidePanel: Story = {
  render: () => (
    <>
      <Modal title="New pain point" onClose={fn()}>
        <TextField label="Scoring model" help={HELP} value="" onChange={fn()} />
      </Modal>
      <SidePanel title="Edit persona" onClose={fn()}>
        <TextField label="Importance weight" help={HELP} value="" onChange={fn()} />
      </SidePanel>
    </>
  ),
  play: async () => {
    for (const [dialog, field] of [["New pain point", "Scoring model"], ["Edit persona", "Importance weight"]]) {
      await userEvent.hover(body().getByRole("button", { name: `Help: ${field}` }));
      const bubble = await body().findByRole("tooltip", { hidden: true });
      await expect(Number(getComputedStyle(bubble).zIndex)).toBeGreaterThan(overlayZIndex(body().getByRole("dialog", { name: dialog })));
      await userEvent.unhover(body().getByRole("button", { name: `Help: ${field}` }));
      await waitFor(() => expect(tip()).not.toBeInTheDocument());
    }
  },
};

export const DarkTheme: Story = { ...OpensAndClosesByMouse, globals: { theme: "dark" } };
