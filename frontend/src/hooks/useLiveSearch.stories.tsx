import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { buildSearchHit, buildSearchResponse, fakeSearchApi } from "../testing/searchFixtures";
import { useLiveSearch } from "./useLiveSearch";

const api = fakeSearchApi((request) => buildSearchResponse([buildSearchHit({ id: request.q, title: `Hit for ${request.q}` })]));

/** Harness: a text box feeding the hook, showing what it reports. */
function Harness() {
  const [q, setQ] = useState("");
  const live = useLiveSearch(q ? { q, scope: "all" } : null, api);
  return (
    <div className="stack">
      <input aria-label="text" value={q} onChange={(e) => setQ(e.target.value)} />
      <output aria-label="titles">{live.response?.hits.map((h) => h.title).join("|")}</output>
      <output aria-label="settled">{String(live.settled)}</output>
    </div>
  );
}

const meta: Meta<typeof Harness> = { title: "Hooks/useLiveSearch", component: Harness };
export default meta;
type Story = StoryObj<typeof Harness>;

/** A result already fetched for the same text is reused: typing, backspacing and typing the same text again asks once. */
export const BackspacingDoesNotRefetch: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const input = canvas.getByLabelText("text");
    await userEvent.type(input, "ab");
    await waitFor(() => expect(canvas.getByLabelText("titles")).toHaveTextContent("Hit for ab"), { timeout: 3000 });
    await expect(api.search).toHaveBeenCalledTimes(1);
    await userEvent.type(input, "c");
    await waitFor(() => expect(canvas.getByLabelText("titles")).toHaveTextContent("Hit for abc"), { timeout: 3000 });
    await userEvent.keyboard("{Backspace}");
    await waitFor(() => expect(canvas.getByLabelText("titles")).toHaveTextContent("Hit for ab"), { timeout: 3000 });
    await expect(api.search).toHaveBeenCalledTimes(2);
  },
};

/** Under two characters nothing is asked and the kept results are not cleared. */
export const ShortTextAsksNothing: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByLabelText("text"), "a");
    await new Promise((resolve) => setTimeout(resolve, 600));
    await expect(api.search).not.toHaveBeenCalled();
    await expect(canvas.getByLabelText("settled")).toHaveTextContent("false");
  },
};
