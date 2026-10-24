import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { Link, MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { ListPageLayout } from "../components/ListPageLayout";
import { RecordHeader } from "../components/RecordHeader";
import { useRestoredRowCount } from "./useListPosition";
import { useUrlText } from "./useUrlFilter";

const PAGE_SIZE = 20;
const TOTAL = 120;

/** A paginated list: rows come from a "server" that honours `limit`, and "Show more" appends a page. */
function ListPage() {
  const limitFor = useRestoredRowCount(PAGE_SIZE);
  const [search, setSearch] = useUrlText("q");
  const [rows, setRows] = useState(() => Array.from({ length: limitFor(0) }, (_, i) => i + 1));
  return (
    <ListPageLayout
      title="Things"
      loadedRows={rows.length}
      filter={<input aria-label="Search" className="input" value={search} onChange={(e) => setSearch(e.target.value)} />}
    >
      <ul style={{ margin: 0 }}>
        {rows.map((n) => (
          <li key={n} style={{ height: 40 }}>
            <Link to={`/things/${n}`}>{`Thing ${n}`}</Link>
          </li>
        ))}
      </ul>
      {rows.length < TOTAL && (
        <button className="btn" onClick={() => setRows((r) => [...r, ...Array.from({ length: PAGE_SIZE }, (_, i) => r.length + i + 1)])}>
          Show more ({rows.length}/{TOTAL})
        </button>
      )}
    </ListPageLayout>
  );
}

function DetailPage() {
  const navigate = useNavigate();
  return (
    <div style={{ height: 400 }}>
      <RecordHeader recordLabel="Thing" title="A thing" back={{ to: "/things", label: "← Things" }} />
      <button className="btn" onClick={() => navigate(-1)}>Browser back</button>
    </div>
  );
}

/**
 * Opening a record and coming back (the browser's Back, or the record's own back link) shows the same rows
 * at the same scroll offset, including rows loaded with "Show more"; a fresh visit starts at the top.
 */
const meta: Meta = {
  title: "Hooks/useListPosition",
  // Saved positions live in sessionStorage, shared by every story in the run; start each story clean.
  loaders: [() => { sessionStorage.clear(); }],
  decorators: [
    (Story) => (
      <MemoryRouter initialEntries={["/things"]}>
        <Story />
      </MemoryRouter>
    ),
  ],
  render: () => (
    <Routes>
      <Route path="/things" element={<ListPage />} />
      <Route path="/things/:id" element={<DetailPage />} />
      <Route path="/elsewhere" element={<p>Elsewhere</p>} />
    </Routes>
  ),
};
export default meta;

type Story = StoryObj;

async function scrollToThing(canvas: ReturnType<typeof within>, name: string) {
  const link = await canvas.findByRole("link", { name });
  link.scrollIntoView({ block: "center" });
  await waitFor(() => expect(window.scrollY).toBeGreaterThan(0));
  return link;
}

export const BrowserBackRestoresRowsAndOffset: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: /Show more/ }));
    await userEvent.click(await canvas.findByRole("button", { name: /Show more/ }));
    const link = await scrollToThing(canvas, "Thing 45");
    const before = window.scrollY;
    await userEvent.click(link);
    await userEvent.click(await canvas.findByRole("button", { name: "Browser back" }));
    await canvas.findByRole("link", { name: "Thing 45" });
    // All 60 rows are back (one request for them), and the offset is where it was.
    await expect(canvas.getAllByRole("link")).toHaveLength(60);
    await waitFor(() => expect(Math.abs(window.scrollY - before)).toBeLessThanOrEqual(2));
  },
};

export const TheRecordsBackLinkRestoresToo: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(await canvas.findByLabelText("Search"), "pump");
    await userEvent.click(await canvas.findByRole("button", { name: /Show more/ }));
    const link = await scrollToThing(canvas, "Thing 15");
    const before = window.scrollY;
    await userEvent.click(link);
    await userEvent.click(await canvas.findByRole("link", { name: "← Things" }));
    await canvas.findByRole("link", { name: "Thing 15" });
    // The list returns with the filter it was left with, not a bare path.
    await expect(canvas.getByLabelText("Search")).toHaveValue("pump");
    await expect(canvas.getAllByRole("link")).toHaveLength(40);
    await waitFor(() => expect(Math.abs(window.scrollY - before)).toBeLessThanOrEqual(2));
  },
};
