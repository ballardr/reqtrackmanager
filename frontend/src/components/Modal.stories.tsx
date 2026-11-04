import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, fn, userEvent, within } from "storybook/test";

import { FormActions } from "./FormActions";
import { Modal } from "./Modal";
import { Popover } from "./Popover";
import { ResultActions } from "./ResultActions";

const meta: Meta<typeof Modal> = {
  title: "Components/Modal",
  component: Modal,
  args: { title: "Delete requirement", onClose: fn(), children: "This cannot be undone." },
};
export default meta;

type Story = StoryObj<typeof Modal>;

export const Default: Story = {
  play: async ({ args }) => {
    // Rendered through a portal into document.body, not canvasElement.
    const body = within(document.body);
    await expect(body.getByRole("dialog", { name: "Delete requirement" })).toBeInTheDocument();
    await expect(body.getByText("This cannot be undone.")).toBeInTheDocument();
    await userEvent.click(body.getByLabelText("Close"));
    await expect(args.onClose).toHaveBeenCalledOnce();
  },
};

export const ClosesOnEscape: Story = {
  play: async ({ args }) => {
    await userEvent.keyboard("{Escape}");
    await expect(args.onClose).toHaveBeenCalledOnce();
  },
};

/** A dialog with no form (a viewer, a picker) still closes on a backdrop click. */
export const ClosesOnBackdropClick: Story = {
  play: async ({ args }) => {
    const body = within(document.body);
    await userEvent.click(body.getByRole("presentation"));
    await expect(args.onClose).toHaveBeenCalledOnce();
  },
};

const FORM_BODY = (
  <>
    <label className="stack">
      Title
      <input className="input" defaultValue="Original" />
    </label>
    <FormActions onCancel={fn()} onSave={fn()} />
  </>
);

/** A dialog that holds a form does nothing on a backdrop click, so a stray click cannot lose the edit. */
export const FormIgnoresBackdropClick: Story = {
  args: { title: "New thing", children: FORM_BODY },
  play: async ({ args }) => {
    const body = within(document.body);
    await userEvent.click(body.getByRole("presentation"));
    await expect(args.onClose).not.toHaveBeenCalled();
    await expect(body.getByRole("dialog", { name: "New thing" })).toBeInTheDocument();
  },
};

/** The header's close button is the only way out of a form dialog: there is no Cancel beside Save. */
export const FormHasCloseButNoCancel: Story = {
  args: { title: "New thing", children: FORM_BODY },
  play: async () => {
    const dialog = within(document.body).getByRole("dialog", { name: "New thing" });
    await expect(within(dialog).getByRole("button", { name: "Save" })).toBeInTheDocument();
    await expect(within(dialog).queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
  },
};

/** Nothing changed: Close leaves at once, without a prompt. */
export const UnchangedFormClosesAtOnce: Story = {
  args: { title: "New thing", children: FORM_BODY },
  play: async ({ args }) => {
    const body = within(document.body);
    await userEvent.click(body.getByLabelText("Close"));
    await expect(args.onClose).toHaveBeenCalledOnce();
    await expect(body.queryByText("Discard unsaved changes?")).not.toBeInTheDocument();
  },
};

/** Close with a change asks first; Keep editing returns to the form with the change intact. */
export const ChangedFormAsksAndKeepEditingKeepsTheChange: Story = {
  args: { title: "New thing", children: FORM_BODY },
  play: async ({ args }) => {
    const body = within(document.body);
    const field = body.getByLabelText("Title");
    await userEvent.type(field, " edited");
    await userEvent.click(body.getByLabelText("Close"));
    await expect(await body.findByText("Discard unsaved changes?")).toBeInTheDocument();
    await expect(args.onClose).not.toHaveBeenCalled();
    await userEvent.click(body.getByRole("button", { name: "Keep editing" }));
    await expect(body.queryByText("Discard unsaved changes?")).not.toBeInTheDocument();
    await expect(field).toHaveValue("Original edited");
  },
};

/** A step that edited a field and then moved to a result view is settled: OK closes, with no prompt. */
function FormThenResult({ onClose }: { onClose: () => void }) {
  const [done, setDone] = useState(false);
  return (
    <Modal title="Import" onClose={onClose}>
      {done ? (
        <>
          <ResultActions onOk={onClose} />
          <p role="status">Imported.</p>
        </>
      ) : (
        <>
          <label className="stack">
            File
            <input className="input" defaultValue="" />
          </label>
          <FormActions onCancel={fn()} onSave={() => setDone(true)} saveLabel="Import" />
        </>
      )}
    </Modal>
  );
}

/** A result view ends with one OK and never asks to discard the earlier step's edits; the unfinished step still asks. */
export const ResultViewClosesWithOkAndNoPrompt: Story = {
  render: (args) => <FormThenResult onClose={args.onClose} />,
  play: async ({ args }) => {
    const body = within(document.body);
    await userEvent.type(body.getByLabelText("File"), "reports.zip");
    await userEvent.click(body.getByLabelText("Close"));
    await expect(await body.findByText("Discard unsaved changes?")).toBeInTheDocument();
    await userEvent.click(body.getByRole("button", { name: "Keep editing" }));
    await userEvent.click(body.getByRole("button", { name: "Import" }));
    await expect(await body.findByText("Imported.")).toBeInTheDocument();
    await expect(body.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
    await userEvent.click(body.getByRole("button", { name: "OK" }));
    await expect(body.queryByText("Discard unsaved changes?")).not.toBeInTheDocument();
    await expect(args.onClose).toHaveBeenCalledOnce();
  },
};

/** Escape goes through the same prompt, and Discard is what finally closes. */
export const EscapeAsksThenDiscardCloses: Story = {
  args: { title: "New thing", children: FORM_BODY },
  play: async ({ args }) => {
    const body = within(document.body);
    await userEvent.type(body.getByLabelText("Title"), "x");
    await userEvent.keyboard("{Escape}");
    await expect(await body.findByText("Discard unsaved changes?")).toBeInTheDocument();
    await expect(args.onClose).not.toHaveBeenCalled();
    await userEvent.click(body.getByRole("button", { name: "Discard changes" }));
    await expect(args.onClose).toHaveBeenCalledOnce();
  },
};

/** An edit that is typed and then undone is compared by value, so it reads as unchanged. */
export const EditUndoneReadsAsUnchanged: Story = {
  args: { title: "New thing", children: FORM_BODY },
  play: async ({ args }) => {
    const body = within(document.body);
    const field = body.getByLabelText("Title");
    await userEvent.type(field, "x");
    await userEvent.type(field, "{Backspace}");
    await userEvent.click(body.getByLabelText("Close"));
    await expect(args.onClose).toHaveBeenCalledOnce();
  },
};

/** A caller that tracks its own state passes `dirty`; it wins over the measured value and guards any dialog. */
export const ExplicitDirtyAsksEvenWithoutAForm: Story = {
  args: { dirty: true },
  play: async ({ args }) => {
    const body = within(document.body);
    await userEvent.click(body.getByRole("presentation"));
    await expect(args.onClose).not.toHaveBeenCalled();
    await userEvent.click(body.getByLabelText("Close"));
    await expect(await body.findByText("Discard unsaved changes?")).toBeInTheDocument();
  },
};

/** The dialog itself stops click propagation, so clicking inside it must
 * NOT trigger the backdrop's close handler. */
export const ClickInsideDoesNotClose: Story = {
  play: async ({ args }) => {
    const body = within(document.body);
    await userEvent.click(body.getByText("This cannot be undone."));
    await expect(args.onClose).not.toHaveBeenCalled();
  },
};

/** Style guide Principle 8: opening the dialog moves
 * focus into it (here, its own Close button, since this story's children
 * have no focusable content of their own) rather than leaving focus
 * wherever it was on the page behind the backdrop. */
export const FocusMovesIntoDialogOnOpen: Story = {
  play: async () => {
    const body = within(document.body);
    await expect(body.getByLabelText("Close")).toHaveFocus();
  },
};

/** A child that sets its own `autoFocus` (e.g. `RichTextEditor`'s
 * link-URL field) wins — the dialog's own "focus something on open"
 * fallback only applies when nothing inside already has focus. */
export const AutoFocusChildWins: Story = {
  args: {
    // autoFocus here is exactly the behaviour under test, not an oversight.
    children: <input className="input" autoFocus placeholder="Link URL" />,
  },
  play: async () => {
    const body = within(document.body);
    await expect(body.getByPlaceholderText("Link URL")).toHaveFocus();
  },
};

/** Tab from the last focusable element wraps back to the first (the Close
 * button); Shift+Tab from the first wraps back to the last — focus never
 * escapes the dialog into the page behind it while it's open. */
export const TabTrapCycles: Story = {
  args: {
    children: (
      <div className="row">
        <button type="button">First action</button>
        <button type="button">Last action</button>
      </div>
    ),
  },
  play: async () => {
    const body = within(document.body);
    const closeButton = body.getByLabelText("Close");
    const lastAction = body.getByRole("button", { name: "Last action" });

    lastAction.focus();
    await userEvent.tab();
    await expect(closeButton).toHaveFocus();

    await userEvent.tab({ shift: true });
    await expect(lastAction).toHaveFocus();
  },
};

function RestoresFocusOnCloseHarness() {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button onClick={() => setOpen(true)}>Open the modal</button>
      {open && (
        <Modal title="Delete requirement" onClose={() => setOpen(false)}>
          This cannot be undone.
        </Modal>
      )}
    </div>
  );
}

/** Closing the dialog (Escape, here) returns focus to whatever triggered
 * it — a keyboard user isn't dropped at the top of the page. */
export const RestoresFocusOnClose: Story = {
  render: () => <RestoresFocusOnCloseHarness />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const trigger = canvas.getByRole("button", { name: "Open the modal" });
    await userEvent.click(trigger);
    await expect(within(document.body).getByRole("dialog")).toBeInTheDocument();

    await userEvent.keyboard("{Escape}");
    await expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument();
    await expect(trigger).toHaveFocus();
  },
};

const LONG_FORM = (
  <div className="stack">
    {Array.from({ length: 40 }, (_, i) => (
      <label key={i} className="stack">
        Field {i + 1}
        <input className="input" />
      </label>
    ))}
  </div>
);

/** `FormActions` inside a `Modal` render in the pinned header (beside the title), not at the end of the
 * form, so Save is reachable at any scroll position; the handlers still belong to the form. */
export const FormActionsSitInThePinnedHeader: Story = {
  args: {
    title: "New thing",
    children: (
      <>
        {LONG_FORM}
        <FormActions onCancel={fn()} onSave={fn()} error="That title is taken." />
      </>
    ),
  },
  play: async () => {
    const body = within(document.body);
    const dialog = body.getByRole("dialog", { name: "New thing" });
    const save = within(dialog).getByRole("button", { name: "Save" });
    const header = dialog.querySelector(".dialog-header")!;
    const scroller = dialog.querySelector(".dialog-body")!;
    await expect(header.contains(save)).toBe(true);
    await expect(header).toHaveTextContent("That title is taken.");
    await expect(within(dialog).queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
    await expect(scroller.scrollHeight).toBeGreaterThan(scroller.clientHeight);
    const before = save.getBoundingClientRect().top;
    scroller.scrollTop = scroller.scrollHeight;
    await expect(save.getBoundingClientRect().top).toBe(before);
  },
};

/** Clicking Save in the header runs the form's own handler, once. */
const headerSave = fn();
export const HeaderSaveRunsTheFormsHandler: Story = {
  args: { title: "New thing" },
  render: (args) => (
    <Modal {...args}>
      {LONG_FORM}
      <FormActions onCancel={fn()} onSave={headerSave} />
    </Modal>
  ),
  play: async () => {
    const body = within(document.body);
    await userEvent.click(body.getByRole("button", { name: "Save" }));
    await expect(headerSave).toHaveBeenCalledTimes(1);
  },
};

function PopoverInsideModalHarness() {
  const [anchor, setAnchor] = useState<HTMLButtonElement | null>(null);
  return (
    <Modal title="Outer" onClose={fn()}>
      <button ref={setAnchor}>Anchor</button>
      {anchor && (
        <Popover anchorRef={{ current: anchor }} title="Inner popover" onClose={fn()}>
          <FormActions onCancel={fn()} onSave={fn()} saveLabel="Add" />
        </Popover>
      )}
    </Modal>
  );
}

/** A `Popover` has no header: its `FormActions` stay inside it instead of jumping to the dialog behind. */
export const PopoverFormActionsStayInThePopover: Story = {
  render: () => <PopoverInsideModalHarness />,
  play: async () => {
    const body = within(document.body);
    const popover = await body.findByRole("dialog", { name: "Inner popover" });
    await expect(within(popover).getByRole("button", { name: "Add" })).toBeInTheDocument();
    const outer = body.getByRole("dialog", { name: "Outer" });
    await expect(outer.querySelector(".dialog-header")!.contains(within(popover).getByRole("button", { name: "Add" }))).toBe(false);
  },
};

export const LightTheme: Story = { globals: { theme: "light" } };
export const DarkTheme: Story = { globals: { theme: "dark" } };
