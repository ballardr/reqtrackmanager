import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import { sortRows } from "./sortRows";

const meta: Meta = { title: "Utils/sortRows" };
export default meta;

type Story = StoryObj;
type Row = { name: string; size: number | null };
const ROWS: Row[] = [{ name: "beta", size: 2 }, { name: "Alpha", size: null }, { name: "gamma", size: 10 }];
const VALUES = { name: (r: Row) => r.name, size: (r: Row) => r.size };

/** Text sorts case-insensitively, in both directions. */
export const Text: Story = {
  render: () => <div />,
  play: async () => {
    await expect(sortRows(ROWS, { key: "name", direction: "asc" }, VALUES).map((r) => r.name)).toEqual(["Alpha", "beta", "gamma"]);
    await expect(sortRows(ROWS, { key: "name", direction: "desc" }, VALUES).map((r) => r.name)).toEqual(["gamma", "beta", "Alpha"]);
  },
};

/** Numbers sort numerically and a row without a value is last when ascending. */
export const NumbersAndEmpty: Story = {
  render: () => <div />,
  play: async () => {
    await expect(sortRows(ROWS, { key: "size", direction: "asc" }, VALUES).map((r) => r.size)).toEqual([2, 10, null]);
  },
};

/** No sort, or an unknown column, keeps the given order. */
export const NoSort: Story = {
  render: () => <div />,
  play: async () => {
    await expect(sortRows(ROWS, null, VALUES)).toBe(ROWS);
    await expect(sortRows(ROWS, { key: "other", direction: "asc" }, VALUES)).toBe(ROWS);
  },
};

/** Digit runs compare by value, so a code with more digits does not sort before a shorter one. */
export const CodesSortByNumber: Story = {
  render: () => <div />,
  play: async () => {
    const codes = [{ name: "ELM-10", size: 1 }, { name: "ELM-9", size: 2 }];
    await expect(sortRows(codes, { key: "name", direction: "asc" }, VALUES).map((r) => r.name)).toEqual(["ELM-9", "ELM-10"]);
  },
};
