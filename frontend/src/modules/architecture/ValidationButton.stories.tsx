import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, fn, userEvent, within } from "storybook/test";

import { buttonHeightViolations } from "../../testing/buttonHeights";
import { withThemeProvider } from "../../testing/storybook-helpers";
import { ValidationButton } from "./ValidationButton";
import type { StateMachineValidationIssue } from "./types";

const ERROR: StateMachineValidationIssue = { severity: "error", code: "no_initial", subject: "", message: "The state machine diagram has no initial state at the top level." };
const UNREACHABLE: StateMachineValidationIssue = { severity: "warning", code: "unreachable", subject: "STE-003", message: "STE-003 cannot be reached from the initial state." };
const AMBIGUOUS: StateMachineValidationIssue = { severity: "warning", code: "ambiguous", subject: "STE-002", message: "STE-002 has two transitions with the same event and no condition (guard)." };

/** Holds the open state the page holds, so the button can be pressed in a story. */
function Host({ issues, onSelect, initiallyOpen = false, focusSubject = null }: {
  issues: StateMachineValidationIssue[]; onSelect: (subject: string) => void; initiallyOpen?: boolean; focusSubject?: string | null;
}) {
  const [open, setOpen] = useState(initiallyOpen);
  return (
    <div className="row" role="toolbar" aria-label="Toolbar" style={{ gap: "var(--space-2)", padding: "var(--space-4)" }}>
      <button type="button" className="btn btn-sm">Save</button>
      <ValidationButton issues={issues} open={open} onOpenChange={setOpen} onSelect={onSelect} focusSubject={focusSubject} />
      <button type="button" className="btn btn-sm">Comment</button>
    </div>
  );
}

const meta: Meta<typeof Host> = {
  title: "Modules/Architecture/ValidationButton",
  component: Host,
  decorators: [withThemeProvider()],
  args: { issues: [], onSelect: fn() },
};
export default meta;
type Story = StoryObj<typeof Host>;

/** No issues: no count, and the list says there is nothing to report. */
export const NoIssues: Story = {
  play: async ({ canvasElement }) => {
    const button = await within(canvasElement).findByRole("button", { name: "Validation: no issues" });
    await expect((button.textContent ?? "").trim()).toBe("Validation");
    await userEvent.click(button);
    await expect(await within(document.body).findByText("Nothing to report.")).toBeInTheDocument();
  },
};

/** Errors take the count's place before warnings do, and a row that names a state selects it. */
export const ErrorsAreCountedAndTheListSelectsAState: Story = {
  args: { issues: [ERROR, UNREACHABLE, AMBIGUOUS] },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const button = await canvas.findByRole("button", { name: "Validation: 1 error and 2 warnings" });
    // The visible word leads the accessible name (the count beside it is the visible number).
    await expect(button.textContent).toBe("Validation1");
    await expect(buttonHeightViolations(canvasElement)).toEqual([]);
    await userEvent.click(button);
    const list = within(await within(document.body).findByRole("group", { name: "Validation issues" }));
    await expect(list.getByText("1 error")).toBeInTheDocument();
    await expect(list.getByText("2 warnings")).toBeInTheDocument();
    // An issue about the whole diagram is text; the others are rows.
    await expect(list.queryByRole("button", { name: /no initial state/ })).not.toBeInTheDocument();
    await userEvent.click(list.getByRole("button", { name: /STE-003 cannot be reached/ }));
    await expect(args.onSelect).toHaveBeenCalledWith("STE-003");
    await expect(within(document.body).queryByRole("group", { name: "Validation issues" })).not.toBeInTheDocument();
  },
};

/** Only warnings: the count takes the warning tone. */
export const WarningsAloneAreCounted: Story = {
  args: { issues: [UNREACHABLE, AMBIGUOUS] },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByRole("button", { name: "Validation: 2 warnings" })).toBeInTheDocument();
  },
};

/** Opened from a state's card, the rows of that state are marked as current. */
export const RowsOfTheFocusedStateAreMarked: Story = {
  args: { issues: [UNREACHABLE, AMBIGUOUS], initiallyOpen: true, focusSubject: "STE-002" },
  play: async () => {
    const list = within(await within(document.body).findByRole("group", { name: "Validation issues" }));
    await expect(list.getByRole("button", { name: /STE-002 has two transitions/ })).toHaveAttribute("aria-current", "true");
    await expect(list.getByRole("button", { name: /STE-003 cannot be reached/ })).not.toHaveAttribute("aria-current");
  },
};

/** The rows are the shared text rows, and the list reads in both themes. */
export const TheListUsesTextRowsInBothThemes: Story = {
  args: { issues: [ERROR, UNREACHABLE], initiallyOpen: true },
  play: async () => {
    const list = within(await within(document.body).findByRole("group", { name: "Validation issues" }));
    const row = list.getByRole("button", { name: /STE-003 cannot be reached/ });
    await expect(row).toHaveClass("menu-item");
    await expect(row).not.toHaveClass("btn");
  },
};
