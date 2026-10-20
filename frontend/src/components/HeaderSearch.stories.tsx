import type { Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError } from "../api/client";
import type { SearchResponse } from "../api/search";
import { buildSearchHit, buildSearchResponse, fakeSearchApi } from "../testing/searchFixtures";
import { HeaderSearch } from "./HeaderSearch";

/** Shows where the router ended up, so a story can assert a navigation without a real page behind it. */
function Where() {
  const location = useLocation();
  return <output aria-label="location">{location.pathname + location.search}</output>;
}

function Bar({ path, api }: { path: string; api: ReturnType<typeof fakeSearchApi> }) {
  return (
    <MemoryRouter initialEntries={[path]}>
      <header className="app-header" style={{ justifyContent: "flex-end" }}>
        <HeaderSearch api={api} />
      </header>
      <Routes>
        <Route path="*" element={<Where />} />
      </Routes>
    </MemoryRouter>
  );
}

const meta: Meta<typeof Bar> = {
  title: "Components/HeaderSearch",
  component: Bar,
  args: { path: "/projects" },
  parameters: { layout: "fullscreen" },
};
export default meta;
type Story = StoryObj<typeof Bar>;

const HITS = [
  buildSearchHit({ id: "r1", title: "Voltage limit" }),
  buildSearchHit({ id: "r2", code: "REQ-002", title: "Voltage ripple" }),
  buildSearchHit({
    type: "risk", type_label: "Risk", id: "k1", code: "RSK-001", title: "Supply voltage sag", status: "identified", status_label: "Identified",
    open_type: "risk", open_id: "k1",
  }),
];

/** Typing shows the top results grouped by record type, each with code, title, type and project, and a footer that
 * names the place searched in the scope's own label (never the word "scope"). */
export const TypingShowsGroupedResultsAndAFooter: Story = {
  args: { api: fakeSearchApi(() => buildSearchResponse(HITS)) },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByRole("combobox", { name: "Search" }), "volt");
    const listbox = await canvas.findByRole("listbox", { name: "Search results" }, { timeout: 3000 });
    await waitFor(() => expect(within(listbox).getAllByRole("option")).toHaveLength(4));
    await expect(within(listbox).getByRole("group", { name: "Requirement" })).toBeInTheDocument();
    await expect(within(listbox).getByRole("group", { name: "Risk" })).toBeInTheDocument();
    await expect(within(listbox).getByText("ALPHA-RSK-001")).toBeInTheDocument();
    await expect(within(listbox).getByText("See all results for ‘volt’ in All projects")).toBeInTheDocument();
    await expect(args.api!.search).toHaveBeenCalledTimes(1);
    await expect(args.api!.search).toHaveBeenCalledWith(
      expect.objectContaining({ q: "volt", scope: "all", limit: 8, counts: false }), expect.anything(),
    );
    // The box carries no scope selector: the place is only named in the footer.
    await expect(canvas.queryByRole("combobox", { name: /scope/i })).not.toBeInTheDocument();
    await expect(canvas.queryByText(/\bscope\b/i)).not.toBeInTheDocument();
  },
};

/** Inside a project the narrowest matching scope is "This project", and the request names that project. */
export const InAProjectItSearchesThatProject: Story = {
  args: { path: "/projects/p1/requirements", api: fakeSearchApi(() => buildSearchResponse(HITS)) },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByRole("combobox", { name: "Search" }), "volt");
    await canvas.findByText("See all results for ‘volt’ in This project");
    await waitFor(() =>
      expect(args.api!.search).toHaveBeenCalledWith(expect.objectContaining({ scope: "project", project_id: "p1" }), expect.anything()),
    );
  },
};

/** Under two characters nothing is requested; the dropdown says so. */
export const NothingIsRequestedUnderTwoCharacters: Story = {
  args: { api: fakeSearchApi(() => buildSearchResponse([])) },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByRole("combobox", { name: "Search" }), "v");
    await expect(await canvas.findByText("Type at least 2 characters to search.")).toBeInTheDocument();
    await new Promise((resolve) => setTimeout(resolve, 500));
    await expect(args.api!.search).not.toHaveBeenCalled();
  },
};

/** The previous results stay on screen (dimmed) while the next request runs, and "No results" is never shown
 * in between: it appears only after a completed request for the current text. */
export const KeepsPreviousResultsWhileTheNextRequestRuns: Story = {
  args: {
    api: fakeSearchApi((request) =>
      request.q === "volt"
        ? buildSearchResponse(HITS)
        : new Promise<SearchResponse>((resolve) => {
            (window as unknown as { releaseSearch: (r: SearchResponse) => void }).releaseSearch = resolve;
          }),
    ),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const input = canvas.getByRole("combobox", { name: "Search" });
    await userEvent.type(input, "volt");
    await canvas.findByRole("option", { name: /Voltage\s*limit/ }, { timeout: 3000 });
    await userEvent.type(input, "age");
    // The second request is in flight: the old results are still there and "No results" has not appeared.
    await waitFor(() => expect((window as unknown as { releaseSearch?: unknown }).releaseSearch).toBeDefined(), { timeout: 3000 });
    await expect(canvas.getByRole("option", { name: /Voltage\s*limit/ })).toBeInTheDocument();
    await expect(canvas.queryByText("No results")).not.toBeInTheDocument();
    (window as unknown as { releaseSearch: (r: SearchResponse) => void }).releaseSearch(buildSearchResponse([]));
    await canvas.findByText("No results");
    await expect(canvas.queryByRole("option", { name: /Voltage\s*limit/ })).not.toBeInTheDocument();
  },
};

/** Arrow keys move through the results and Enter opens the highlighted one. */
export const ArrowKeysAndEnterOpenAResult: Story = {
  args: { api: fakeSearchApi(() => buildSearchResponse(HITS)) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const input = canvas.getByRole("combobox", { name: "Search" });
    await userEvent.type(input, "volt");
    await canvas.findByRole("option", { name: /Voltage\s*ripple/ }, { timeout: 3000 });
    await userEvent.keyboard("{ArrowDown}{ArrowDown}");
    await expect(input).toHaveAttribute("aria-activedescendant", expect.stringContaining("-opt-1"));
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(canvas.getByLabelText("location")).toHaveTextContent("/projects/p1/requirements/r2"));
  },
};

/** Enter with nothing highlighted opens the search page, carrying the text and scope in the URL. */
export const EnterWithNothingHighlightedOpensThePage: Story = {
  args: { path: "/projects/p1", api: fakeSearchApi(() => buildSearchResponse(HITS)) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByRole("combobox", { name: "Search" }), "volt{Enter}");
    await waitFor(() => expect(canvas.getByLabelText("location")).toHaveTextContent("/search?q=volt&scope=project&project=p1"));
  },
};

/** The visible Search button submits too (it is the form's accessible submit). */
export const TheSearchButtonSubmits: Story = {
  args: { api: fakeSearchApi(() => buildSearchResponse(HITS)) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByRole("combobox", { name: "Search" }), "volt");
    await userEvent.click(canvas.getByRole("button", { name: "Search" }));
    await waitFor(() => expect(canvas.getByLabelText("location")).toHaveTextContent("/search?q=volt&scope=all"));
  },
};

/** Escape closes the dropdown; a second Escape clears the box. */
export const EscapeClosesThenClears: Story = {
  args: { api: fakeSearchApi(() => buildSearchResponse(HITS)) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const input = canvas.getByRole("combobox", { name: "Search" });
    await userEvent.type(input, "volt");
    await canvas.findByRole("listbox", { name: "Search results" }, { timeout: 3000 });
    await userEvent.keyboard("{Escape}");
    await expect(canvas.queryByRole("listbox")).not.toBeInTheDocument();
    await expect(input).toHaveValue("volt");
    await userEvent.keyboard("{Escape}");
    await expect(input).toHaveValue("");
  },
};

/** `/` focuses the box from anywhere that is not a text field. */
export const SlashFocusesTheBox: Story = {
  args: { api: fakeSearchApi(() => buildSearchResponse(HITS)) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.keyboard("/");
    await expect(canvas.getByRole("combobox", { name: "Search" })).toHaveFocus();
  },
};

/** A failed search says so in the dropdown instead of showing an empty list. */
export const ATimeoutIsSaid: Story = {
  args: {
    api: fakeSearchApi(() => {
      throw new ApiError(408, "The search took too long. Narrow the search and try again.");
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByRole("combobox", { name: "Search" }), "volt");
    await canvas.findByText("The search took too long. Narrow the search and try again.", undefined, { timeout: 3000 });
  },
};

/** Below the nav-rail breakpoint the box collapses to a search icon that opens it full width, with a close button. */
export const NarrowWindowsCollapseToAnIconButton: Story = {
  args: { api: fakeSearchApi(() => buildSearchResponse(HITS)) },
  beforeEach: () => {
    spyOn(window, "matchMedia").mockImplementation(
      (query: string) =>
        ({ matches: true, media: query, addEventListener: () => undefined, removeEventListener: () => undefined }) as unknown as MediaQueryList,
    );
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("combobox", { name: "Search" })).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Open search" }));
    const input = await canvas.findByRole("combobox", { name: "Search" });
    await waitFor(() => expect(input).toHaveFocus());
    await userEvent.click(canvas.getByRole("button", { name: "Close search" }));
    await expect(canvas.getByRole("button", { name: "Open search" })).toBeInTheDocument();
  },
};

/** Searching too fast is answered by the server's 429; the dropdown says to wait instead of showing an empty list. */
export const TooManySearchesSaysToWait: Story = {
  args: {
    api: fakeSearchApi(() => {
      throw new ApiError(429, "You are searching too fast. Wait 2 seconds and try again.");
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByRole("combobox", { name: "Search" }), "volt");
    await canvas.findByText("You are searching too fast. Wait a moment and try again.", undefined, { timeout: 3000 });
  },
};
