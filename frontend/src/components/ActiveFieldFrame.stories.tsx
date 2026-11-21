import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { ActiveFieldFrame, ActiveFieldToolbar } from "./ActiveFieldFrame";

/** The frame that shows a rich text field's toolbar only while focus is inside the field. */
const meta: Meta = { title: "Components/ActiveFieldFrame" };
export default meta;

type Story = StoryObj;

/** A field with a toolbar of two buttons, a text area and a control outside the frame. */
function Field() {
  return (
    <>
      <ActiveFieldFrame className="stack">
        <ActiveFieldToolbar>
          <div role="toolbar" aria-label="Formatting">
            <button type="button">Bold</button>
            <button type="button">Italic</button>
          </div>
        </ActiveFieldToolbar>
        <textarea aria-label="Notes" />
        <button type="button">Switch view</button>
      </ActiveFieldFrame>
      <button type="button">Outside</button>
    </>
  );
}

/** Hidden until the field is worked in; focus on the field's own switch counts; focus elsewhere hides it. */
export const ShowsToolbarOnlyWhileFocusIsInsideTheFrame: Story = {
  render: () => <Field />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("toolbar")).toBeNull();
    await userEvent.click(canvas.getByRole("textbox", { name: "Notes" }));
    await expect(await canvas.findByRole("toolbar", { name: "Formatting" })).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Outside" }));
    await waitFor(() => expect(canvas.queryByRole("toolbar")).toBeNull());
    canvas.getByRole("button", { name: "Switch view" }).focus();
    await expect(await canvas.findByRole("toolbar", { name: "Formatting" })).toBeInTheDocument();
  },
};

/** Pressing a toolbar button does not take focus from the text area, and Escape does not hide the toolbar. */
export const PressingAButtonKeepsTheToolbarAndTheFocus: Story = {
  render: () => <Field />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const area = canvas.getByRole("textbox", { name: "Notes" });
    await userEvent.click(area);
    await userEvent.click(await canvas.findByRole("button", { name: "Bold" }));
    await expect(area).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    await expect(canvas.getByRole("toolbar", { name: "Formatting" })).toBeInTheDocument();
  },
};

/** The hidden toolbar is out of the tab order: Tab from outside the field lands on the text area, not a hidden button. */
export const HiddenToolbarIsNotInTheTabOrder: Story = {
  render: () => <Field />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.tab();
    await expect(canvas.getByRole("textbox", { name: "Notes" })).toHaveFocus();
    // Shift+Tab goes back through the now shown toolbar: it is in the order only while it is visible.
    await userEvent.tab({ shift: true });
    await expect(canvas.getByRole("button", { name: "Italic" })).toHaveFocus();
  },
};

/** A toolbar outside any frame is always visible, and a nested frame follows the outer one. */
export const ToolbarOutsideAFrameIsAlwaysShown: Story = {
  render: () => (
    <ActiveFieldToolbar>
      <div role="toolbar" aria-label="Always">
        <button type="button">Bold</button>
      </div>
    </ActiveFieldToolbar>
  ),
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("toolbar", { name: "Always" })).toBeInTheDocument();
  },
};

export const NestedFrameFollowsTheOuterFrame: Story = {
  render: () => (
    <ActiveFieldFrame>
      <button type="button">Outer switch</button>
      <ActiveFieldFrame>
        <ActiveFieldToolbar>
          <div role="toolbar" aria-label="Inner">
            <button type="button">Bold</button>
          </div>
        </ActiveFieldToolbar>
      </ActiveFieldFrame>
    </ActiveFieldFrame>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("toolbar")).toBeNull();
    canvas.getByRole("button", { name: "Outer switch" }).focus();
    await expect(await canvas.findByRole("toolbar", { name: "Inner" })).toBeInTheDocument();
  },
};
