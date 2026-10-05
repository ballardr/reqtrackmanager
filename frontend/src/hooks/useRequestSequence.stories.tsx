import type { Meta, StoryObj } from "@storybook/react-vite";
import { useRef, useState } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { useRequestSequence } from "./useRequestSequence";

/**
 * Harness for the race `useRequestSequence` guards: two loads start, and the
 * *first* (older) one finishes last. Only the newest load's result may be
 * shown.
 */
function Harness() {
  const beginLoad = useRequestSequence();
  const pending = useRef<Record<string, () => void>>({});
  const [shown, setShown] = useState("");

  function startLoad(label: string) {
    const isLatest = beginLoad();
    new Promise<void>((resolve) => {
      pending.current[label] = resolve;
    }).then(() => {
      if (isLatest()) setShown(label);
    });
  }

  return (
    <div className="stack">
      <button onClick={() => startLoad("old")}>Start old load</button>
      <button onClick={() => startLoad("new")}>Start new load</button>
      <button onClick={() => pending.current.new?.()}>Finish new</button>
      <button onClick={() => pending.current.old?.()}>Finish old</button>
      <output>{shown}</output>
    </div>
  );
}

const meta: Meta<typeof Harness> = {
  title: "Hooks/useRequestSequence",
  component: Harness,
};
export default meta;

type Story = StoryObj<typeof Harness>;

export const OlderResponseLandingLastIsIgnored: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Start old load" }));
    await userEvent.click(canvas.getByRole("button", { name: "Start new load" }));
    await userEvent.click(canvas.getByRole("button", { name: "Finish new" }));
    await waitFor(() => expect(canvas.getByRole("status")).toHaveTextContent("new"));
    await userEvent.click(canvas.getByRole("button", { name: "Finish old" }));
    // Give the stale resolution a tick; the newer result must survive it.
    await new Promise((resolve) => setTimeout(resolve, 50));
    await expect(canvas.getByRole("status")).toHaveTextContent("new");
  },
};
