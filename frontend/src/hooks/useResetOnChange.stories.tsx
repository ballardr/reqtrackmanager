import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import { useResetOnChange } from "./useResetOnChange";

function Harness() {
  const [filter, setFilter] = useState("a");
  const [page, setPage] = useState(1);
  useResetOnChange([filter], () => setPage(1));
  return (
    <div>
      <button onClick={() => setPage((p) => p + 1)}>Next page</button>
      <button onClick={() => setFilter("b")}>Change filter</button>
      <p data-testid="state">{`${filter}:${page}`}</p>
    </div>
  );
}

const meta: Meta = { title: "Hooks/useResetOnChange", component: Harness };
export default meta;

type Story = StoryObj;

export const ResetsOnlyWhenTheListedValueChanges: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByTestId("state")).toHaveTextContent("a:1");
    await userEvent.click(canvas.getByRole("button", { name: "Next page" }));
    await userEvent.click(canvas.getByRole("button", { name: "Next page" }));
    await expect(canvas.getByTestId("state")).toHaveTextContent("a:3");
    await userEvent.click(canvas.getByRole("button", { name: "Change filter" }));
    await expect(canvas.getByTestId("state")).toHaveTextContent("b:1");
  },
};
