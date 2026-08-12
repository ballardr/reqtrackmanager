import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import type { ReportChapter } from "../api/types";
import { ReportChapterListEditor } from "./ReportChapterListEditor";

function Interactive() {
  const [list, setList] = useState<ReportChapter[]>([
    { title: "Scope", body: "What this project covers." },
    { title: "Assumptions", body: "Known constraints going in." },
  ]);
  return <ReportChapterListEditor label="Appendices" list={list} setList={setList} />;
}

const meta: Meta<typeof Interactive> = {
  title: "Components/ReportChapterListEditor",
  component: Interactive,
};
export default meta;

type Story = StoryObj<typeof Interactive>;

export const TwoChapters: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByDisplayValue("Scope")).toBeInTheDocument();
    await expect(canvas.getByDisplayValue("Assumptions")).toBeInTheDocument();
  },
};

// Each chapter renders as its own `.card`, containing exactly three
// unlabelled icon buttons in a fixed order: move up, move down, delete.
// Scoping by card + button index avoids depending on lucide's internal
// icon markup.
function chapterCards(canvasElement: HTMLElement): HTMLElement[] {
  return Array.from(canvasElement.querySelectorAll<HTMLElement>(".card"));
}

export const Reorder: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const titleInputs = () => canvas.getAllByPlaceholderText("Chapter title") as HTMLInputElement[];
    await expect(titleInputs()[0]).toHaveValue("Scope");
    // Second chapter's "move up" button (first of its three icon buttons) swaps it with the first.
    const secondCardButtons = within(chapterCards(canvasElement)[1]).getAllByRole("button");
    await userEvent.click(secondCardButtons[0]);
    await expect(titleInputs()[0]).toHaveValue("Assumptions");
  },
};

export const AddAndRemoveChapter: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /add chapter/i }));
    await expect(canvas.getAllByPlaceholderText("Chapter title")).toHaveLength(3);
    // Delete is the third (last) icon button in the first chapter's card.
    const firstCardButtons = within(chapterCards(canvasElement)[0]).getAllByRole("button");
    await userEvent.click(firstCardButtons[2]);
    await expect(canvas.getAllByPlaceholderText("Chapter title")).toHaveLength(2);
  },
};

export const EmptyList: Story = {
  render: () => {
    function Empty() {
      const [list, setList] = useState<ReportChapter[]>([]);
      return <ReportChapterListEditor label="Appendices" list={list} setList={setList} />;
    }
    return <Empty />;
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByPlaceholderText("Chapter title")).not.toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...TwoChapters, globals: { theme: "light" } };
export const DarkTheme: Story = { ...TwoChapters, globals: { theme: "dark" } };
