import type { Meta, StoryObj } from "@storybook/react-vite";
import { useRef, useState } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { useLatest } from "./useLatest";

/**
 * Harness reproducing the bug `useLatest` exists for: "Start save" begins
 * an async action that resumes later (like a post-create `reload()`); the
 * filter is changed while it's pending; when it resumes it reports the
 * filter it would list with — via the ref (latest) and via its own stale
 * closure (the bug) side by side.
 */
function Harness() {
  const [filter, setFilter] = useState("");
  const latestFilter = useLatest(filter);
  const resume = useRef<() => void>(() => {});
  const [result, setResult] = useState("");

  function startSave() {
    const captured = filter;
    new Promise<void>((resolve) => {
      resume.current = resolve;
    }).then(() => setResult(`latest:${latestFilter.current} closure:${captured}`));
  }

  return (
    <div className="stack">
      <input aria-label="Filter" value={filter} onChange={(e) => setFilter(e.target.value)} />
      <button onClick={startSave}>Start save</button>
      <button onClick={() => resume.current()}>Finish save</button>
      <output>{result}</output>
    </div>
  );
}

const meta: Meta<typeof Harness> = {
  title: "Hooks/useLatest",
  component: Harness,
};
export default meta;

type Story = StoryObj<typeof Harness>;

export const ReadsFilterChangedWhileAwaiting: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Start save" }));
    await userEvent.type(canvas.getByRole("textbox", { name: "Filter" }), "E2E Approval");
    await userEvent.click(canvas.getByRole("button", { name: "Finish save" }));
    await waitFor(() => expect(canvas.getByRole("status")).toHaveTextContent("latest:E2E Approval closure:"));
  },
};
