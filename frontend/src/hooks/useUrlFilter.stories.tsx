import type { Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter, useLocation } from "react-router-dom";
import { expect, userEvent, within } from "storybook/test";

import { cycleSort } from "../components/sortState";
import { useUrlChoice, useUrlFlag, useUrlList, useUrlSort, useUrlText } from "./useUrlFilter";

const STATUSES = ["draft", "approved"] as const;
const SORT_KEYS = ["name", "status"] as const;

function Harness() {
  const [search, setSearch] = useUrlText("q");
  const [status, setStatus] = useUrlChoice("status", STATUSES);
  const [archived, setArchived] = useUrlFlag("archived");
  const [open, setOpen] = useUrlFlag("open", true);
  const [tags, setTags] = useUrlList("tag");
  const [sort, setSort] = useUrlSort(SORT_KEYS);
  const { search: query } = useLocation();
  return (
    <div className="stack">
      <input aria-label="Search" value={search} onChange={(e) => setSearch(e.target.value)} />
      <button onClick={() => setStatus("draft")}>Draft</button>
      <button onClick={() => setArchived(true)}>Show archived</button>
      <button onClick={() => setOpen(false)}>All items</button>
      <button onClick={() => setTags(["a", "b"])}>Tag a and b</button>
      <button onClick={() => setSort((current) => cycleSort(current, "name"))}>Sort by name</button>
      <button onClick={() => { setSearch(""); setStatus(""); setArchived(false); setTags([]); }}>Clear all</button>
      <output aria-label="URL">{query}</output>
      <output aria-label="State">{`${search}|${status}|${archived}|${open}|${tags.join(",")}|${sort ? `${sort.key}:${sort.direction}` : "none"}`}</output>
    </div>
  );
}

/**
 * A list's filters live in the query string: a value at its default is absent, other parameters are kept,
 * and several setters called by one handler all take effect.
 */
const meta: Meta<typeof Harness> = {
  title: "Hooks/useUrlFilter",
  component: Harness,
  decorators: [(Story) => <MemoryRouter initialEntries={["/list?keep=1"]}><Story /></MemoryRouter>],
};
export default meta;

type Story = StoryObj<typeof Harness>;

export const FiltersAreWrittenToTheUrl: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByLabelText("State")).toHaveTextContent("|false|true||none");
    await userEvent.type(canvas.getByLabelText("Search"), "pump");
    await userEvent.click(canvas.getByRole("button", { name: "Draft" }));
    await userEvent.click(canvas.getByRole("button", { name: "Show archived" }));
    await userEvent.click(canvas.getByRole("button", { name: "All items" }));
    await userEvent.click(canvas.getByRole("button", { name: "Tag a and b" }));
    await userEvent.click(canvas.getByRole("button", { name: "Sort by name" }));
    await expect(canvas.getByLabelText("State")).toHaveTextContent("pump|draft|true|false|a,b|name:asc");
    const query = new URLSearchParams(canvas.getByLabelText("URL").textContent ?? "");
    await expect(query.get("keep")).toBe("1");
    await expect(query.get("q")).toBe("pump");
    await expect(query.get("open")).toBe("0");
    await expect(query.getAll("tag")).toEqual(["a", "b"]);
    await expect(query.get("order")).toBe("asc");
  },
};

export const SettersInOneHandlerAllTakeEffect: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByLabelText("Search"), "pump");
    await userEvent.click(canvas.getByRole("button", { name: "Draft" }));
    await userEvent.click(canvas.getByRole("button", { name: "Show archived" }));
    await userEvent.click(canvas.getByRole("button", { name: "Tag a and b" }));
    await userEvent.click(canvas.getByRole("button", { name: "Clear all" }));
    await expect(canvas.getByLabelText("State")).toHaveTextContent("|false|true||none");
    await expect(canvas.getByLabelText("URL")).toHaveTextContent("?keep=1");
  },
};

export const SortCyclesThroughDescendingToUnsorted: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const sortButton = canvas.getByRole("button", { name: "Sort by name" });
    await userEvent.click(sortButton);
    await expect(canvas.getByLabelText("State")).toHaveTextContent("name:asc");
    await userEvent.click(sortButton);
    await expect(canvas.getByLabelText("State")).toHaveTextContent("name:desc");
    await userEvent.click(sortButton);
    await expect(canvas.getByLabelText("State")).toHaveTextContent("none");
  },
};
