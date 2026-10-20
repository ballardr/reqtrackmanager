import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import { Modal } from "./Modal";
import { buildChip, openTagPicker } from "../testing/tagsFixtures";
import { TagInput } from "./TagInput";

/** Holds the chosen names in state, as a form does, inside a form so Enter-submits can be seen. */
function Harness({ initial = [], onSubmit, ...rest }: Omit<React.ComponentProps<typeof TagInput>, "value" | "onChange"> & {
  initial?: string[];
  onSubmit?: () => void;
}) {
  const [value, setValue] = useState<string[]>(initial);
  return (
    <form onSubmit={(e) => { e.preventDefault(); onSubmit?.(); }}>
      <TagInput {...rest} value={value} onChange={setValue} />
      <output aria-label="Chosen">{value.join("|")}</output>
    </form>
  );
}

const SUGGESTIONS = [buildChip("Safety", "#c53030"), buildChip("Release 2"), buildChip("Security")];

/**
 * The tag picker: chosen tags as chips and a `[+]` that opens a popover with the text box. Free projects may coin a tag; restricted
 * projects accept only listed tags.
 */
const meta: Meta<typeof Harness> = {
  title: "Components/TagInput",
  component: Harness,
  args: { suggestions: SUGGESTIONS },
};
export default meta;

type Story = StoryObj<typeof Harness>;

const chosen = (canvas: ReturnType<typeof within>) => canvas.getByLabelText("Chosen").textContent;
const body = () => within(document.body);

/** No tags: just the `[+]` chip, no text box in the row. */
export const NoTagsShowsOnlyThePlusButton: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const add = canvas.getByRole("button", { name: "Add tag" });
    await expect(add).toHaveAttribute("aria-haspopup", "dialog");
    await expect(add).toHaveAttribute("aria-expanded", "false");
    await expect(canvas.queryByRole("combobox")).not.toBeInTheDocument();
  },
};

export const PickingFromTheListAddsTheTag: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(await openTagPicker(canvas), "sec");
    await userEvent.click(await body().findByRole("option", { name: "Security" }));
    await expect(chosen(canvas)).toBe("Security");
    await expect(canvas.getByRole("button", { name: "Remove tag Security" })).toBeInTheDocument();
  },
};

/** The `[+]` is the same height as the tag chips beside it. */
export const PlusIsTheSameHeightAsTheChips: Story = {
  args: { initial: ["Safety", "Release 2"] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const add = canvas.getByRole("button", { name: "Add tag" }).getBoundingClientRect();
    for (const chip of canvasElement.querySelectorAll<HTMLElement>(".tag-chip")) {
      await expect(Math.abs(chip.getBoundingClientRect().height - add.height)).toBeLessThan(1);
    }
    await expect(Math.abs(add.width - add.height)).toBeLessThan(1);
  },
};

/** The popover stays open after an add, cleared and focused, so several tags go in one visit. */
export const SeveralTagsInOneVisit: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const input = await openTagPicker(canvas);
    await userEvent.type(input, "one{Enter}");
    await expect(input).toHaveValue("");
    await expect(input).toHaveFocus();
    await userEvent.type(input, "two{Enter}");
    await expect(chosen(canvas)).toBe("one|two");
    await expect(canvas.getByRole("button", { name: "Add tag" })).toHaveAttribute("aria-expanded", "true");
  },
};

/** Done, Escape and a click outside close the popover; focus returns to the `[+]`. */
export const DoneAndEscapeClose: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await openTagPicker(canvas);
    await userEvent.click(body().getByRole("button", { name: "Done" }));
    await expect(body().queryByRole("dialog", { name: "Add tag" })).not.toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Add tag" })).toHaveFocus();
    await openTagPicker(canvas);
    await userEvent.keyboard("{Escape}"); // closes the suggestion list first
    await userEvent.keyboard("{Escape}");
    await expect(body().queryByRole("dialog", { name: "Add tag" })).not.toBeInTheDocument();
  },
};

/** Typing a new name in a free project offers to add it; Enter adds it without submitting the form. */
export const AFreeProjectCanCoinATag: Story = {
  args: { restricted: false },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const input = await openTagPicker(canvas);
    await userEvent.type(input, "Brand new");
    await expect(await body().findByRole("option", { name: 'Add tag "Brand new"' })).toBeInTheDocument();
    await userEvent.keyboard("{Enter}");
    await expect(chosen(canvas)).toBe("Brand new");
  },
};

/** The listed spelling wins: typing `safety` adds `Safety`, once. */
export const NamesMatchTheListIgnoringCase: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const input = await openTagPicker(canvas);
    await userEvent.type(input, "safety{Enter}");
    await userEvent.type(input, "SAFETY{Enter}");
    await expect(chosen(canvas)).toBe("Safety");
  },
};

export const ACommaCommitsTheTypedTag: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(await openTagPicker(canvas), "one,two;");
    await expect(chosen(canvas)).toBe("one|two");
  },
};

/** A restricted project is picker only: an unlisted name is refused with who can add it. */
export const ARestrictedProjectRefusesAnUnlistedTag: Story = {
  args: { restricted: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const input = await openTagPicker(canvas);
    await expect(input).toHaveAttribute("placeholder", "Choose a tag…");
    await userEvent.type(input, "Made up{Enter}");
    await expect(await body().findByRole("alert")).toHaveTextContent("Ask a project administrator");
    await expect(chosen(canvas)).toBe("");
    await userEvent.clear(input);
    await userEvent.type(input, "release 2{Enter}");
    await expect(chosen(canvas)).toBe("Release 2");
  },
};

export const ATooLongNameIsRefused: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(await openTagPicker(canvas), `${"x".repeat(41)}{Enter}`);
    await expect(await body().findByRole("alert")).toHaveTextContent("at most 40 characters");
    await expect(chosen(canvas)).toBe("");
  },
};

export const RemovingAChipAndBackspace: Story = {
  args: { initial: ["Safety", "Release 2"] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Remove tag Safety" }));
    await expect(chosen(canvas)).toBe("Release 2");
    await openTagPicker(canvas);
    await userEvent.keyboard("{Backspace}");
    await expect(chosen(canvas)).toBe("");
  },
};

/** Enter in the box never submits the surrounding form. */
export const EnterDoesNotSubmitTheForm: Story = {
  args: { onSubmit: () => { throw new Error("the form was submitted"); } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(await openTagPicker(canvas), "abc{Enter}");
    await expect(chosen(canvas)).toBe("abc");
  },
};

/** Many chips wrap onto further lines; the `[+]` follows the last chip. */
export const ALongTagListWraps: Story = {
  args: { initial: Array.from({ length: 14 }, (_, i) => `Release ${i + 10}`) },
  decorators: [(Story) => <div style={{ width: 320 }}><Story /></div>],
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("button", { name: "Add tag" })).toBeVisible();
  },
};

/** Inside a modal, Escape closes only the picker and Enter never submits the modal's form. */
export const OpenInsideAModal: Story = {
  render: () => (
    <Modal title="New record" onClose={() => { throw new Error("the modal was closed"); }}>
      <Harness suggestions={SUGGESTIONS} onSubmit={() => { throw new Error("the form was submitted"); }} />
    </Modal>
  ),
  play: async () => {
    const scope = body();
    const add = await scope.findByRole("button", { name: "Add tag" });
    await userEvent.click(add);
    const input = await scope.findByRole("combobox", { name: "Tags" });
    await userEvent.type(input, "abc{Enter}");
    await expect(scope.getByLabelText("Chosen").textContent).toBe("abc");
    // The suggestion list is already closed after an add, so one Escape closes the picker and leaves the modal open.
    await userEvent.keyboard("{Escape}");
    await expect(scope.queryByRole("dialog", { name: "Add tag" })).not.toBeInTheDocument();
    await expect(scope.getByRole("dialog", { name: "New record" })).toBeInTheDocument();
  },
};

export const ReadOnlyShowsTheChipsOnly: Story = {
  args: { initial: ["Safety"], disabled: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Safety", { selector: ".chip__label" })).toBeInTheDocument();
    await expect(canvas.queryByRole("combobox")).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Add tag" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Remove tag Safety" })).not.toBeInTheDocument();
  },
};
