import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import { buildChip } from "../testing/tagsFixtures";
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
 * The tag picker: chosen tags as chips and one text box. Free projects may coin a tag; restricted
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

export const PickingFromTheListAddsTheTag: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByRole("combobox", { name: "Tags" }), "sec");
    await userEvent.click(await canvas.findByRole("option", { name: "Security" }));
    await expect(chosen(canvas)).toBe("Security");
    await expect(canvas.getByRole("button", { name: "Remove tag Security" })).toBeInTheDocument();
  },
};

/** Typing a new name in a free project offers to add it; Enter adds it without submitting the form. */
export const AFreeProjectCanCoinATag: Story = {
  args: { restricted: false },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const input = canvas.getByRole("combobox", { name: "Tags" });
    await userEvent.type(input, "Brand new");
    await expect(await canvas.findByRole("option", { name: 'Add tag "Brand new"' })).toBeInTheDocument();
    await userEvent.keyboard("{Enter}");
    await expect(chosen(canvas)).toBe("Brand new");
  },
};

/** The listed spelling wins: typing `safety` adds `Safety`, once. */
export const NamesMatchTheListIgnoringCase: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const input = canvas.getByRole("combobox", { name: "Tags" });
    await userEvent.type(input, "safety{Enter}");
    await userEvent.type(input, "SAFETY{Enter}");
    await expect(chosen(canvas)).toBe("Safety");
  },
};

export const ACommaCommitsTheTypedTag: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByRole("combobox", { name: "Tags" }), "one,two;");
    await expect(chosen(canvas)).toBe("one|two");
  },
};

/** A restricted project is picker only: an unlisted name is refused with who can add it. */
export const ARestrictedProjectRefusesAnUnlistedTag: Story = {
  args: { restricted: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const input = canvas.getByRole("combobox", { name: "Tags" });
    await expect(input).toHaveAttribute("placeholder", "Choose a tag…");
    await userEvent.type(input, "Made up{Enter}");
    await expect(await canvas.findByRole("alert")).toHaveTextContent("Ask a project administrator");
    await expect(chosen(canvas)).toBe("");
    await userEvent.clear(input);
    await userEvent.type(input, "release 2{Enter}");
    await expect(chosen(canvas)).toBe("Release 2");
  },
};

export const ATooLongNameIsRefused: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByRole("combobox", { name: "Tags" }), `${"x".repeat(41)}{Enter}`);
    await expect(await canvas.findByRole("alert")).toHaveTextContent("at most 40 characters");
    await expect(chosen(canvas)).toBe("");
  },
};

export const RemovingAChipAndBackspace: Story = {
  args: { initial: ["Safety", "Release 2"] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Remove tag Safety" }));
    await expect(chosen(canvas)).toBe("Release 2");
    await userEvent.click(canvas.getByRole("combobox", { name: "Tags" }));
    await userEvent.keyboard("{Backspace}");
    await expect(chosen(canvas)).toBe("");
  },
};

/** Enter in the box never submits the surrounding form. */
export const EnterDoesNotSubmitTheForm: Story = {
  args: { onSubmit: () => { throw new Error("the form was submitted"); } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByRole("combobox", { name: "Tags" }), "abc{Enter}");
    await expect(chosen(canvas)).toBe("abc");
  },
};

export const ReadOnlyShowsTheChipsOnly: Story = {
  args: { initial: ["Safety"], disabled: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Safety", { selector: ".chip__label" })).toBeInTheDocument();
    await expect(canvas.queryByRole("combobox")).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Remove tag Safety" })).not.toBeInTheDocument();
  },
};
