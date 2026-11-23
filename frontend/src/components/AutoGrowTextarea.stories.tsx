import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import { AutoGrowTextarea } from "./AutoGrowTextarea";

/** `AutoGrowTextarea` is controlled (`value`/`onChange`); this harness supplies the state a page would own. */
function Harness(props: { placeholder?: string; maxVisibleLines?: number }) {
  const [value, setValue] = useState("");
  return <AutoGrowTextarea placeholder={props.placeholder} maxVisibleLines={props.maxVisibleLines} value={value} onChange={setValue} />;
}

const meta: Meta<typeof Harness> = {
  title: "Components/AutoGrowTextarea",
  component: Harness,
  args: { placeholder: "Reasoning" },
};
export default meta;

type Story = StoryObj<typeof Harness>;

export const RendersAndAcceptsInput: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const textarea = canvas.getByPlaceholderText("Reasoning") as HTMLTextAreaElement;
    await userEvent.type(textarea, "Because customers requested it.");
    await expect(textarea).toHaveValue("Because customers requested it.");
  },
};

/** Content within the height cap grows the textarea to fit — no internal
 * scrollbar needed, `scrollHeight` and `clientHeight` stay in step. */
export const GrowsToFitContentWithinTheCap: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const textarea = canvas.getByPlaceholderText("Reasoning") as HTMLTextAreaElement;
    const oneLineHeight = textarea.clientHeight;

    await userEvent.type(textarea, "Line one{enter}Line two{enter}Line three");
    await expect(textarea.clientHeight).toBeGreaterThan(oneLineHeight);
    // Everything typed still fits — no internal scroll yet (small integer
    // tolerance for sub-pixel rounding between the two measurements).
    await expect(textarea.scrollHeight).toBeLessThanOrEqual(textarea.clientHeight + 2);
  },
};

/** Capped at about 8 lines by default; content past the cap scrolls internally. A small `maxVisibleLines` (3)
 * keeps the fixture short. */
export const CapsHeightAndScrollsInternallyPastMaxVisibleLines: Story = {
  args: { maxVisibleLines: 3 },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const textarea = canvas.getByPlaceholderText("Reasoning") as HTMLTextAreaElement;
    await userEvent.type(
      textarea,
      "Line one{enter}Line two{enter}Line three{enter}Line four{enter}Line five{enter}Line six"
    );
    // Content exceeds the 3-line cap, so the element's own scrollHeight
    // (everything typed) now exceeds its clientHeight (capped) — the
    // overflow scrolls inside the element instead of growing past the cap.
    await expect(textarea.scrollHeight).toBeGreaterThan(textarea.clientHeight);
  },
};

/** The cap is derived from the app's own resolved line-height, not a fixed
 * pixel number — a smaller `maxVisibleLines` produces a proportionally
 * smaller cap, not the same cap regardless of the prop. */
export const MaxVisibleLinesControlsTheCap: Story = {
  render: () => {
    function TwoCaps() {
      const [a, setA] = useState("Line one\nLine two\nLine three\nLine four\nLine five\nLine six\nLine seven\nLine eight\nLine nine\nLine ten");
      const [b, setB] = useState("Line one\nLine two\nLine three\nLine four\nLine five\nLine six\nLine seven\nLine eight\nLine nine\nLine ten");
      return (
        <div className="stack">
          <AutoGrowTextarea aria-label="Short cap" maxVisibleLines={2} value={a} onChange={setA} />
          <AutoGrowTextarea aria-label="Tall cap" maxVisibleLines={6} value={b} onChange={setB} />
        </div>
      );
    }
    return <TwoCaps />;
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const shortCap = canvas.getByLabelText("Short cap") as HTMLTextAreaElement;
    const tallCap = canvas.getByLabelText("Tall cap") as HTMLTextAreaElement;
    await expect(shortCap.clientHeight).toBeLessThan(tallCap.clientHeight);
  },
};

export const LightTheme: Story = { globals: { theme: "light" } };
export const DarkTheme: Story = { globals: { theme: "dark" } };
