import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { useLoadOnChange } from "./useLoadOnChange";

function Harness() {
  const [filter, setFilter] = useState("a");
  const [calls, setCalls] = useState<string[]>([]);
  const [unrelated, setUnrelated] = useState(0);

  // `load` reads `unrelated` without listing it: a change to it must not reload.
  useLoadOnChange(() => {
    setTimeout(() => setCalls((c) => [...c, `${filter}:${unrelated}`]), 0);
  }, [filter]);

  return (
    <div>
      <button onClick={() => setFilter("b")}>Change filter</button>
      <button onClick={() => setUnrelated((n) => n + 1)}>Change something else</button>
      <p data-testid="calls">{calls.join(",")}</p>
    </div>
  );
}

const meta: Meta = { title: "Hooks/useLoadOnChange", component: Harness };
export default meta;

type Story = StoryObj;

export const LoadsOnMountAndWhenDepsChangeOnly: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByTestId("calls")).toHaveTextContent("a:0"));
    await userEvent.click(canvas.getByRole("button", { name: "Change something else" }));
    await userEvent.click(canvas.getByRole("button", { name: "Change filter" }));
    // The reload sees the latest values of everything, including the one that is not a dependency.
    await waitFor(() => expect(canvas.getByTestId("calls")).toHaveTextContent("a:0,b:1"));
  },
};
