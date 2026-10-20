import type { Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { ApiError } from "../api/client";
import { buildSearchHit, buildSearchResponse, fakeSearchApi } from "../testing/searchFixtures";
import { buildUser, withAuth } from "../testing/storybook-helpers";
import { SearchPage } from "./SearchPage";

/** Shows the router's URL so a story can assert state kept in it. */
function Url() {
  const location = useLocation();
  return <output aria-label="url">{location.search}</output>;
}

function Page({ entry, api }: { entry: string | { pathname: string; search: string; state?: unknown }; api: ReturnType<typeof fakeSearchApi> }) {
  return (
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route
          path="/search"
          element={
            <>
              <SearchPage api={api} />
              <Url />
            </>
          }
        />
      </Routes>
    </MemoryRouter>
  );
}

const meta: Meta<typeof Page> = {
  title: "Pages/SearchPage",
  component: Page,
  parameters: { layout: "fullscreen" },
  decorators: [withAuth(buildUser())],
};
export default meta;
type Story = StoryObj<typeof Page>;

const LONG = "An exceptionally long record title that keeps going well past any sensible single line of text so that the row has to wrap";

const HITS = [
  buildSearchHit({
    id: "r1", title: "Voltage limit",
    snippet: { field_key: "description", field_label: "Description", text: "The supply voltage must stay within limits", ranges: [[11, 18]] },
  }),
  buildSearchHit({
    type: "persona", type_label: "Persona", id: "pe1", code: "PER-001", title: "Field technician", project_id: null, project_name: null,
    project_code: null, status: "active", status_label: "Active", open_project_id: "p1",
  }),
  buildSearchHit({ id: "r3", code: "REQ-003", title: LONG }),
  buildSearchHit({
    type: "research_finding", type_label: "Research finding", id: "f1", code: "FND-001", title: "Voltage confuses installers",
    open_type: "engagement", open_id: "e1",
  }),
];

/** Results are links to each record's own page, with code, title, type, status, where it lives and the matching field's text. */
export const ResultsShowCodeTitleStatusPlaceAndSnippet: Story = {
  args: { entry: "/search?q=volt&scope=all", api: fakeSearchApi(() => buildSearchResponse(HITS)) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("heading", { name: "Results for ‘volt’" });
    const link = await canvas.findByRole("link", { name: /Voltage\s*limit/ });
    await expect(link).toHaveAttribute("href", "/projects/p1/requirements/r1");
    await expect(canvas.getByText("ALPHA-REQ-001")).toBeInTheDocument();
    await expect(canvas.getByText(/Description:/)).toBeInTheDocument();
    await expect(canvas.getByText("ACME-PER-001")).toBeInTheDocument(); // organisation-owned: qualified by the organisation
    await expect(canvas.getByText("Organisation record")).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: /Voltage\s*confuses\s*installers/ })).toHaveAttribute("href");
    await expect(canvas.getByText("4 results")).toBeInTheDocument();
  },
};

/** Long titles wrap inside their row; nothing is cut off. */
export const LongTitlesWrap: Story = {
  args: { entry: "/search?q=exceptionally&scope=all", api: fakeSearchApi(() => buildSearchResponse([HITS[2]])) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("link", { name: /exceptionally/ });
  },
};

/** Changing the Scope filter re-runs the search and updates the URL. */
export const ChangingTheScopeReRunsTheSearch: Story = {
  args: {
    entry: {
      pathname: "/search", search: "?q=volt&scope=project&project=p1",
      state: { scopes: [{ value: "project", label: "This project", projectId: "p1" }, { value: "all", label: "All projects" }] },
    },
    api: fakeSearchApi(() => buildSearchResponse(HITS)),
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("link", { name: /Voltage\s*limit/ });
    const scope = canvas.getByRole("combobox", { name: "Scope" });
    await expect(scope).toHaveValue("project:p1");
    await userEvent.selectOptions(scope, "All projects");
    await waitFor(() => expect(canvas.getByLabelText("url")).toHaveTextContent("?q=volt"));
    await expect(canvas.getByLabelText("url")).not.toHaveTextContent("scope=project");
    await waitFor(() => expect(args.api.search).toHaveBeenLastCalledWith(expect.objectContaining({ scope: "all" }), expect.anything()));
  },
};

/** The Organisation filter appears only for a viewer in more than one organisation. */
export const OrganisationFilterNeedsTwoOrganisations: Story = {
  args: { entry: "/search?q=volt", api: fakeSearchApi(() => buildSearchResponse(HITS)) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("link", { name: /Voltage\s*limit/ });
    await expect(canvas.queryByRole("combobox", { name: "Organisation" })).not.toBeInTheDocument();
  },
};

export const OrganisationFilterShowsForTwo: Story = {
  args: {
    entry: "/search?q=volt",
    api: fakeSearchApi(() =>
      buildSearchResponse(HITS, { organizations: [{ id: "o1", name: "Acme", code: "ACME" }, { id: "o2", name: "Globex", code: "GLOBEX" }] }),
    ),
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const filter = await canvas.findByRole("combobox", { name: "Organisation" });
    await userEvent.selectOptions(filter, "Globex");
    await waitFor(() => expect(args.api.search).toHaveBeenLastCalledWith(expect.objectContaining({ organization_ids: ["o2"] }), expect.anything()));
    await expect(canvas.getByLabelText("url")).toHaveTextContent("org=o2");
  },
};

/** Record types show only those that matched, each with its count, and picking one narrows the results. */
export const TypeFilterListsMatchedTypesWithCounts: Story = {
  args: { entry: "/search?q=volt", api: fakeSearchApi(() => buildSearchResponse(HITS)) },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("link", { name: /Voltage\s*limit/ });
    await userEvent.click(canvas.getByRole("button", { name: "Record type" }));
    const group = within(document.body).getByRole("group", { name: "Record type" });
    await expect(within(group).getByRole("checkbox", { name: "Requirement (2)" })).toBeInTheDocument();
    await expect(within(group).getByRole("checkbox", { name: "Persona (1)" })).toBeInTheDocument();
    await userEvent.click(within(group).getByRole("checkbox", { name: "Persona (1)" }));
    await waitFor(() => expect(args.api.search).toHaveBeenLastCalledWith(expect.objectContaining({ types: ["persona"] }), expect.anything()));
  },
};

/** The field picker has its own filter box, ID and Title are locked on, and a choice is remembered in the URL. */
export const FieldPickerIsFilterableAndKeepsIdAndTitle: Story = {
  args: { entry: "/search?q=volt", api: fakeSearchApi(() => buildSearchResponse(HITS)) },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("link", { name: /Voltage\s*limit/ });
    await userEvent.click(canvas.getByRole("button", { name: "Search fields" }));
    const group = within(document.body).getByRole("group", { name: "Search fields" });
    await expect(within(group).getByRole("checkbox", { name: "ID" })).toBeDisabled();
    await userEvent.type(within(document.body).getByRole("searchbox", { name: "Filter Search fields" }), "mitig");
    await expect(within(group).queryByRole("checkbox", { name: "Reasoning" })).not.toBeInTheDocument();
    await userEvent.click(within(group).getByRole("checkbox", { name: "Mitigation" }));
    await waitFor(() => expect(canvas.getByLabelText("url")).toHaveTextContent("fields=id%2Ctitle%2Ctags%2Cmitigation"));
    await waitFor(() =>
      expect(args.api.search).toHaveBeenLastCalledWith(expect.objectContaining({ fields: ["id", "title", "tags", "mitigation"] }), expect.anything()),
    );
  },
};

/** Types that declare none of the selected fields are named, never silently missing. */
export const NamesTypesThatWereNotSearched: Story = {
  args: {
    entry: "/search?q=volt&fields=description",
    api: fakeSearchApi(() => buildSearchResponse(HITS, { not_searched: [{ key: "risk", label: "Risk" }] })),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByText("Not searched: Risk (no selected field)");
  },
};

/** Nothing found says so and suggests what to change. */
export const EmptyResultsSuggestWhatToChange: Story = {
  args: { entry: "/search?q=zzzz", api: fakeSearchApi(() => buildSearchResponse([])) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByText("Nothing found");
    await expect(canvas.getByText(/widen the scope/)).toBeInTheDocument();
  },
};

/** Without enough text the page asks for more and makes no request. */
export const TooLittleTextMakesNoRequest: Story = {
  args: { entry: "/search?q=v", api: fakeSearchApi(() => buildSearchResponse([])) },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await canvas.findByText("Type at least 2 characters to search records across your projects.");
    await expect(args.api.search).not.toHaveBeenCalled();
  },
};

/** A search that is too slow says to narrow it. */
export const ATimeoutSaysToNarrowTheSearch: Story = {
  args: {
    entry: "/search?q=volt",
    api: fakeSearchApi(() => {
      throw new ApiError(408, "The search took too long. Narrow the search and try again.");
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("alert");
  },
};

/** Past the depth limit the page says to refine the search. */
export const TheDepthLimitSaysToRefine: Story = {
  args: {
    entry: "/search?q=volt",
    api: fakeSearchApi(() => buildSearchResponse(HITS, { total: 500, total_capped: true })),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByText("500+ results");
  },
};

/** In one project the page offers to include the organisation's records, on by default; unchecking it is sent to the server and kept in the URL. */
export const ProjectSearchCanIncludeOrganisationRecords: Story = {
  args: {
    entry: { pathname: "/search", search: "?q=volt&scope=project&project=p1", state: { scopes: [{ value: "project", label: "This project", projectId: "p1" }] } },
    api: fakeSearchApi(() => buildSearchResponse(HITS)),
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const box = await canvas.findByRole("checkbox", { name: "Include organisation records" });
    await expect(box).toBeChecked();
    await userEvent.click(box);
    await waitFor(() => expect(canvas.getByLabelText("url")).toHaveTextContent("orgrecords=0"));
    await waitFor(() => expect(args.api.search).toHaveBeenLastCalledWith(expect.objectContaining({ include_organization_records: false }), expect.anything()));
  },
};

/** The choice is not offered where it does not apply: all-projects searches always include them. */
export const AllProjectsSearchHasNoOrganisationRecordsChoice: Story = {
  args: { entry: "/search?q=volt&scope=all", api: fakeSearchApi(() => buildSearchResponse(HITS)) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("link", { name: /Voltage\s*limit/ });
    await expect(canvas.queryByRole("checkbox", { name: "Include organisation records" })).not.toBeInTheDocument();
  },
};

export const DarkTheme: Story = { ...ResultsShowCodeTitleStatusPlaceAndSnippet, globals: { theme: "dark" } };
