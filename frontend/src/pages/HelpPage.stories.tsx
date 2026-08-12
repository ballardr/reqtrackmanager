import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { HelpPage } from "./HelpPage";

const meta: Meta<typeof HelpPage> = {
  title: "Pages/HelpPage",
  component: HelpPage,
};
export default meta;

type Story = StoryObj<typeof HelpPage>;

// A single story only: `mermaid.initialize`/`mermaid.run` (called by
// HelpPage's own effect) hold internal singleton state keyed by diagram id,
// which collides across repeated mounts in the same browser session —
// multiple stories here each re-running mermaid.run() against the six
// concatenated help docs' diagrams was flaky (stale DOM references thrown
// as unhandled rejections), even though each is a legitimate, correct
// document individually. One story still exercises the real render path
// (including every mermaid diagram in the help content) without the
// cross-story collision.
export const Default: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("How this app is organised")).toBeInTheDocument();
    // "Organisations" renders as its own <strong>, so the sentence is split
    // across sibling text nodes — match on the <li>'s combined textContent
    // instead of a single-node text query.
    await expect(
      canvas.getByText((_, element) => element?.tagName === "LI" && /Organisations.*are the top tenant boundary/.test(element.textContent ?? ""))
    ).toBeInTheDocument();
  },
};
