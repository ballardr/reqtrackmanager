import type { Meta, StoryObj } from "@storybook/react-vite";
import { useRef, useState } from "react";
import { expect, fn, userEvent, within } from "storybook/test";

import { Popover } from "./Popover";

/** `Popover` takes a live `anchorRef` to position against and has no
 * header chrome of its own — every story drives it through this harness
 * (a trigger button + the "New group" popover body from the style guide's
 * own mockup) rather than static `args`, since there's no meaningful way
 * to render it without a mounted anchor element. */
function PopoverHarness({ onClose, initialOpen = true }: { onClose: () => void; initialOpen?: boolean }) {
  const [open, setOpen] = useState(initialOpen);
  const anchorRef = useRef<HTMLButtonElement>(null);

  function close() {
    setOpen(false);
    onClose();
  }

  return (
    <div style={{ padding: "4rem" }}>
      <button ref={anchorRef} onClick={() => setOpen((o) => !o)}>
        + New group
      </button>
      {open && (
        <Popover anchorRef={anchorRef} title="New group" onClose={close}>
          <label className="stack" style={{ gap: "var(--space-1)" }}>
            Group name
            <input className="input" placeholder="e.g. Firmware" />
          </label>
          <div className="row" style={{ justifyContent: "flex-end" }}>
            <button type="button" onClick={close}>
              Cancel
            </button>
            <button type="button" className="btn-primary">
              Create
            </button>
          </div>
        </Popover>
      )}
    </div>
  );
}

const meta: Meta<typeof PopoverHarness> = {
  title: "Components/Popover",
  component: PopoverHarness,
  args: { onClose: fn() },
};
export default meta;

type Story = StoryObj<typeof PopoverHarness>;

export const Default: Story = {
  play: async () => {
    // Rendered through a portal into document.body, not canvasElement.
    const body = within(document.body);
    await expect(body.getByRole("dialog", { name: "New group" })).toBeInTheDocument();
    await expect(body.getByPlaceholderText("e.g. Firmware")).toBeInTheDocument();
  },
};

export const ClosesOnEscape: Story = {
  play: async ({ args }) => {
    await userEvent.keyboard("{Escape}");
    await expect(args.onClose).toHaveBeenCalledOnce();
    await expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument();
  },
};

/** No backdrop (page content behind a popover stays interactive), but a
 * click anywhere outside the bubble and its anchor still closes it — the
 * click-outside-to-dismiss half of a lightweight popover. */
export const ClosesOnOutsideClick: Story = {
  play: async ({ args }) => {
    await userEvent.click(document.body);
    await expect(args.onClose).toHaveBeenCalledOnce();
  },
};

export const ClickInsideDoesNotClose: Story = {
  play: async ({ args }) => {
    const body = within(document.body);
    await userEvent.click(body.getByPlaceholderText("e.g. Firmware"));
    await expect(args.onClose).not.toHaveBeenCalled();
  },
};

/** Style guide Principle 8, same as `Modal`: opening
 * moves focus into the popover (here, its first field) rather than
 * leaving it on the trigger button behind it. */
export const FocusMovesIntoPopoverOnOpen: Story = {
  play: async () => {
    const body = within(document.body);
    await expect(body.getByPlaceholderText("e.g. Firmware")).toHaveFocus();
  },
};

/** Tab from the last focusable element (Create) wraps back to the first
 * (the name field); focus never escapes into the page behind it while
 * open, same trap `Modal`/`SidePanel` share via `dialogA11y.ts`. */
export const TabTrapCycles: Story = {
  play: async () => {
    const body = within(document.body);
    const nameField = body.getByPlaceholderText("e.g. Firmware");
    const createButton = body.getByRole("button", { name: "Create" });

    createButton.focus();
    await userEvent.tab();
    await expect(nameField).toHaveFocus();

    await userEvent.tab({ shift: true });
    await expect(createButton).toHaveFocus();
  },
};

/** Closing the popover (Escape, here) returns focus to the trigger button
 * that opened it. Starts closed and opens via a real click — every other
 * story starts pre-opened for a simpler `play`, but restoration is only a
 * meaningful assertion when the "previously focused element" captured on
 * open is genuinely the trigger, which requires actually clicking it
 * rather than mounting already-open. */
export const RestoresFocusOnClose: Story = {
  args: { initialOpen: false },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const trigger = canvas.getByRole("button", { name: "+ New group" });

    await userEvent.click(trigger);
    await expect(within(document.body).getByRole("dialog")).toBeInTheDocument();

    await userEvent.keyboard("{Escape}");
    await expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument();
    await expect(trigger).toHaveFocus();
  },
};

function TallPopoverNearTheBottom({ anchorTop }: { anchorTop: string }) {
  const anchorRef = useRef<HTMLButtonElement>(null);
  return (
    <div id="popover-scroller" style={{ height: "100vh", overflowY: "auto" }}>
      <div style={{ height: "300vh", paddingTop: anchorTop }}>
        <button ref={anchorRef}>Open the tall list</button>
        <Popover anchorRef={anchorRef} title="Tall list" onClose={fn()}>
          {Array.from({ length: 40 }, (_, i) => (
            <label key={i} className="row">
              <input type="checkbox" aria-label={`Option ${i + 1}`} />
              Option {i + 1}
            </label>
          ))}
        </Popover>
      </div>
    </div>
  );
}

/** Content taller than the room on either side is capped to the roomier side and scrolls inside, so the
 * last option is reachable by scrolling the popover rather than lying below the fold. */
export const TallContentIsCappedToTheViewportAndScrolls: Story = {
  render: () => <TallPopoverNearTheBottom anchorTop="calc(100vh - 6rem)" />,
  play: async () => {
    const bubble = within(document.body).getByRole("dialog", { name: "Tall list" });
    const rect = bubble.getBoundingClientRect();
    await expect(rect.top).toBeGreaterThanOrEqual(0);
    await expect(rect.bottom).toBeLessThanOrEqual(window.innerHeight);
    await expect(bubble.scrollHeight).toBeGreaterThan(bubble.clientHeight);
    const last = within(bubble).getByLabelText("Option 40");
    last.scrollIntoView();
    const lastRect = last.getBoundingClientRect();
    await expect(lastRect.bottom).toBeLessThanOrEqual(window.innerHeight);
  },
};

/** The popover is `position: fixed`; when the page scrolls inside a container it follows its anchor. */
export const FollowsItsAnchorWhenAnAncestorScrolls: Story = {
  render: () => <TallPopoverNearTheBottom anchorTop="10rem" />,
  play: async () => {
    const bubble = within(document.body).getByRole("dialog", { name: "Tall list" });
    const anchor = within(document.body).getByRole("button", { name: "Open the tall list" });
    const gapBefore = bubble.getBoundingClientRect().top - anchor.getBoundingClientRect().bottom;
    document.getElementById("popover-scroller")!.scrollTop = 40;
    await new Promise((resolve) => setTimeout(resolve, 100));
    const gapAfter = bubble.getBoundingClientRect().top - anchor.getBoundingClientRect().bottom;
    await expect(Math.abs(gapAfter - gapBefore)).toBeLessThan(2);
  },
};

export const LightTheme: Story = { globals: { theme: "light" } };
export const DarkTheme: Story = { globals: { theme: "dark" } };
