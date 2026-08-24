import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import { cycleSort, SortableHeader, type SortState } from "./SortableHeader";

/** A minimal two-column table so the `<th>` reads naturally in isolation —
 * `SortableHeader` is always used inside a real `<thead><tr>`, never alone. */
function Demo({ initial }: { initial: SortState<"name" | "status"> | null }) {
  const [sort, setSort] = useState<SortState<"name" | "status"> | null>(initial);
  return (
    <table>
      <thead>
        <tr>
          <SortableHeader label="Name" sortKey="name" sort={sort} onSort={(key) => setSort((s) => cycleSort(s, key))} />
          <SortableHeader label="Status" sortKey="status" sort={sort} onSort={(key) => setSort((s) => cycleSort(s, key))} />
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>Alpha</td>
          <td>Draft</td>
        </tr>
      </tbody>
    </table>
  );
}

const meta: Meta<typeof Demo> = {
  title: "Components/SortableHeader",
  component: Demo,
  args: { initial: null },
};
export default meta;

type Story = StoryObj<typeof Demo>;

export const Unsorted: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const button = canvas.getByRole("button", { name: "Name" });
    await expect(button).toBeInTheDocument();
    await expect(button.closest("th")).toHaveAttribute("aria-sort", "none");
  },
};

export const AscendingAfterClick: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const button = canvas.getByRole("button", { name: "Name" });
    await userEvent.click(button);
    const th = button.closest("th");
    await expect(th).toHaveAttribute("aria-sort", "ascending");
  },
};

export const DescendingAfterTwoClicks: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const button = canvas.getByRole("button", { name: "Name" });
    await userEvent.click(button);
    await userEvent.click(button);
    const th = button.closest("th");
    await expect(th).toHaveAttribute("aria-sort", "descending");
  },
};

export const BackToUnsortedAfterThreeClicks: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const button = canvas.getByRole("button", { name: "Name" });
    await userEvent.click(button);
    await userEvent.click(button);
    await userEvent.click(button);
    const th = button.closest("th");
    await expect(th).toHaveAttribute("aria-sort", "none");
  },
};

export const OtherColumnActive: Story = {
  args: { initial: { key: "status", direction: "desc" } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const nameButton = canvas.getByRole("button", { name: "Name" });
    await expect(nameButton.closest("th")).toHaveAttribute("aria-sort", "none");
    const statusButton = canvas.getByRole("button", { name: "Status" });
    await expect(statusButton.closest("th")).toHaveAttribute("aria-sort", "descending");
  },
};

export const LightTheme: Story = { args: { initial: { key: "name", direction: "asc" } }, globals: { theme: "light" } };
export const DarkTheme: Story = { args: { initial: { key: "name", direction: "asc" } }, globals: { theme: "dark" } };
