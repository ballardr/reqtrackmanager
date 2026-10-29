import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildGrid, buildRecordColumns } from "../../testing/recordTablesFixtures";
import { buildProject, buildScoringScheme, buildUser, withRouter, withStatefulAuth, withToast } from "../../testing/storybook-helpers";
import { scoreValue, scoringSummary } from "./painPointScoringFixtures";
import { ProjectPainPointsPage } from "./ProjectPainPointsPage";
import type { EffectivePainPointType, PainPoint, PainPointScoringSummary } from "./types";
import { openListMenu, chooseExport } from "../../testing/listActionsMenu";

const PROJECT_ID = "project-1";

const TYPES: EffectivePainPointType[] = [
  { id: "type-operator", name: "Operator", display_order: 0, is_enabled: true, source: "org", definition: null },
];

function painPoint(overrides: Partial<PainPoint> = {}): PainPoint {
  return {
    id: "pain-point-1", project_id: PROJECT_ID, unique_code: "PP-001", pain_point_type_id: "type-operator", pain_point_type_name: "Operator",
    creator_id: "user-1", is_archived: false, archived_at: null, archived_by: null,
    title: "Report delays under poor connectivity", description: "Field reports queue for days.",
    source: "Operator interviews", impact: "Decisions are made on stale data.", evidence: "12 reports last month.",
    priority: "high", status: "submitted", owner: null, date_identified: "2026-01-05", is_intentional: false, is_locked: false,
    created_at: "2026-01-05T09:00:00Z", updated_at: "2026-01-05T09:00:00Z",
    ...overrides,
  };
}

function mockPageApis(painPoints: PainPoint[], scoring: PainPointScoringSummary[] = [], { canScore = false } = {}) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.endsWith("/records/pain_point/columns")) return buildRecordColumns({ label: "Pain points" });
    if (path.includes("/records/pain_point/grid")) return buildGrid();
    if (path.endsWith("/pain-point-scoring-targets")) return { can_score: canScore, available_targets: [] };
    if (path === `/api/v1/projects/${PROJECT_ID}`) return buildProject({ id: PROJECT_ID, organization_id: "org-1" });
    if (path === `/api/v1/projects/${PROJECT_ID}/scoring-schemes/pain_point`) return buildScoringScheme();
    if (path.startsWith(`/api/v1/projects/${PROJECT_ID}/modules/context_strategy/pain-point-scores`)) {
      const model = new URL(path, "http://localhost").searchParams.get("model_key") ?? "sxfxc";
      return { model_key: model, model_source: "system", rollup: "weighted_average", items: scoring };
    }
    if (path.startsWith(`/api/v1/projects/${PROJECT_ID}/modules/context_strategy/pain-point-types`)) return TYPES;
    if (path.startsWith(`/api/v1/projects/${PROJECT_ID}/modules/context_strategy/pain-points`)) return painPoints;
    throw new Error(`Unmocked GET: ${path}`);
  });
}

const meta: Meta<typeof ProjectPainPointsPage> = {
  title: "Modules/ContextStrategy/ProjectPainPointsPage",
  component: ProjectPainPointsPage,
  decorators: [
    // `parameters.query` lets a story open the page the way a report figure's link does (`?open=1&blocker=1`).
    (Story, context) =>
      withRouter(
        `/projects/${PROJECT_ID}/modules/context_strategy/pain-points${context.parameters.query ?? ""}`,
        "/projects/:projectId/modules/context_strategy/pain-points",
      )(Story, context),
    // `ViewToggle`'s `useViewMode` reads the view mode through `useUiPreference`, which needs a real `useAuth()` user.
    withStatefulAuth(buildUser()),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof ProjectPainPointsPage>;

export const ListsPainPoints: Story = {
  beforeEach: () => mockPageApis([painPoint(), painPoint({ id: "pain-point-2", title: "Competitive pricing pressure", status: "triaged" })]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Report delays under poor connectivity")).toBeInTheDocument());
    await expect(canvas.getByText("Competitive pricing pressure")).toBeInTheDocument();
    // The record code has its own column, so a Pain Point can be named in conversation.
    await expect(canvas.getByRole("columnheader", { name: "Code" })).toBeInTheDocument();
    await expect(canvas.getAllByText(/PP-001/).length).toBeGreaterThan(0);
  },
};

/** The Score column renders the roll-up, the Blocker and Intentional badges follow the title; the Score column sorts unscored last. */
export const ShowsScoresAndBlockerAndSorts: Story = {
  beforeEach: () =>
    mockPageApis(
      [
        painPoint({ id: "pp-low", title: "Low scoring problem" }),
        painPoint({ id: "pp-high", title: "High scoring problem", is_intentional: true }),
        painPoint({ id: "pp-none", title: "Unscored problem" }),
      ],
      [
        scoringSummary({ pain_point_id: "pp-low", scope: "all_personas", counted: 1, score: scoreValue({ raw: 2, band_label: "Low", band_tone: "muted", normalised: 0.1 }) }),
        scoringSummary({
          pain_point_id: "pp-high", scope: "all_personas", counted: 1, is_blocker: true, blocker_labels: ["Field Technician"],
          score: scoreValue({ raw: 18, band_label: "Critical", band_tone: "danger", normalised: 0.9 }),
        }),
        scoringSummary({ pain_point_id: "pp-none" }),
      ],
    ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Critical · 18")).toBeInTheDocument());
    // Blocker and Intentional follow the title (in the first column); the Score cell holds only the score.
    const row = canvas.getByText("High scoring problem").closest("tr")!;
    const cells = within(row).getAllByRole("cell");
    await expect(within(cells[0]).getByText("Blocker")).toBeInTheDocument();
    await expect(within(cells[0]).getByText("Intentional")).toBeInTheDocument();
    await expect(within(cells[cells.length - 1]).queryByText("Blocker")).not.toBeInTheDocument();
    // Scoped to the table: the Scoring filter's "Not scored" option has the same text.
    await expect(within(canvas.getByRole("table", { name: "Pain Points" })).getByText("Not scored")).toBeInTheDocument();

    const titles = () => canvas.getAllByRole("button", { name: /problem/ }).map((b) => b.textContent?.replace("Intentional", "").replace("Blocker", ""));
    const scoreHeader = canvas.getByRole("button", { name: "Score" });
    await userEvent.click(scoreHeader); // ascending
    await waitFor(() => expect(titles()).toEqual(["Low scoring problem", "High scoring problem", "Unscored problem"]));
    await userEvent.click(scoreHeader); // descending: unscored still last
    await waitFor(() => expect(titles()).toEqual(["High scoring problem", "Low scoring problem", "Unscored problem"]));
  },
};

/** The gear on the Score column holds the model switcher; it refetches the roll-up and does not sort. */
export const ScoreSettingsGearRefetchesScores: Story = {
  beforeEach: () => mockPageApis([painPoint()]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // The selects are not on the page until the gear is opened.
    await waitFor(() => canvas.getByRole("button", { name: /^Score settings: / }));
    await expect(canvas.queryByRole("combobox", { name: "Scoring model" })).not.toBeInTheDocument();
    const gear = canvas.getByRole("button", { name: /^Score settings: / });
    await expect(gear).toHaveAttribute("aria-haspopup", "dialog");
    await expect(gear).toHaveAccessibleName(/combined by Weighted average/);
    await userEvent.click(gear);
    const body = within(document.body);
    await userEvent.selectOptions(await body.findByRole("combobox", { name: "Scoring model" }), "sxf");
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(expect.stringContaining("model_key=sxf")));
    await expect(body.getByRole("combobox", { name: "Combine personas by" })).toBeInTheDocument();
    // Pressing the gear never changes the sort.
    await expect(canvas.getByRole("columnheader", { name: /Score/ })).toHaveAttribute("aria-sort", "none");
    // A changed model is marked on the closed gear.
    await expect(gear).toHaveClass("btn-marked");
  },
};

export const HideIntentionalFilter: Story = {
  beforeEach: () => mockPageApis([painPoint({ title: "Fixable problem" }), painPoint({ id: "pp-2", title: "Tier limit problem", is_intentional: true })]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText(/Tier limit problem/)).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("checkbox", { name: "Hide intentional limitations" }));
    await waitFor(() => expect(canvas.queryByText(/Tier limit problem/)).not.toBeInTheDocument());
    await expect(canvas.getByText("Fixable problem")).toBeInTheDocument();
  },
};

/** The list opens on open Pain Points only, with the filter shown ticked. */
export const OpensOnOpenPainPointsByDefault: Story = {
  beforeEach: () => mockPageApis([
    painPoint({ id: "pp-open", title: "Still open problem" }),
    painPoint({ id: "pp-done", title: "Already addressed problem", status: "addressed" }),
  ]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Still open problem")).toBeInTheDocument());
    await expect(canvas.queryByText("Already addressed problem")).not.toBeInTheDocument();
    const openOnly = canvas.getByRole("checkbox", { name: "Open only" });
    await expect(openOnly).toBeChecked();
    await userEvent.click(openOnly);
    await expect(await canvas.findByText("Already addressed problem")).toBeInTheDocument();
  },
};

/** A link that names a status shows that slice, so the default never produces an empty list. */
export const AStatusLinkStartsWithOpenOnlyOff: Story = {
  parameters: { query: "?status=addressed" },
  beforeEach: () => mockPageApis([
    painPoint({ id: "pp-open", title: "Still open problem" }),
    painPoint({ id: "pp-done", title: "Already addressed problem", status: "addressed" }),
  ]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Already addressed problem")).toBeInTheDocument());
    await expect(canvas.queryByText("Still open problem")).not.toBeInTheDocument();
    await expect(canvas.getByRole("checkbox", { name: "Open only" })).not.toBeChecked();
  },
};

/** `open=0` turns the default off. */
export const OpenZeroShowsEverything: Story = {
  parameters: { query: "?open=0" },
  beforeEach: () => mockPageApis([painPoint({ id: "pp-done", title: "Already addressed problem", status: "addressed" })]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Already addressed problem")).toBeInTheDocument());
    await expect(canvas.getByRole("checkbox", { name: "Open only" })).not.toBeChecked();
  },
};

/** When only the default hides everything, the empty state says why. */
export const EmptyBecauseOfOpenOnlySaysSo: Story = {
  beforeEach: () => mockPageApis([painPoint({ id: "pp-done", title: "Already addressed problem", status: "addressed" })]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText(/^No open Pain Points\. Untick Open only/)).toBeInTheDocument());
  },
};

export const EmptyState: Story = {
  beforeEach: () => mockPageApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No Pain Points recorded for this project yet.")).toBeInTheDocument());
  },
};

export const OpenCreateModal: Story = {
  beforeEach: () => mockPageApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "New Pain Point" }));
    await userEvent.click(canvas.getByRole("button", { name: "New Pain Point" }));
    // `PainPointFormModal` portals to `document.body`.
    await expect(within(document.body).getByRole("heading", { name: "New Pain Point" })).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...ListsPainPoints };
export const DarkTheme: Story = { ...ListsPainPoints, globals: { theme: "dark" } };

/** A report figure's link opens the list already filtered, and every pre-set filter is a visible control. */
export const OpensPreFilteredFromAReportFigure: Story = {
  parameters: { query: "?open=1&intentional=hide&blocker=1" },
  beforeEach: () =>
    mockPageApis(
      [
        painPoint({ id: "pp-block", title: "Blocking problem" }),
        painPoint({ id: "pp-fine", title: "Fine problem" }),
        painPoint({ id: "pp-int", title: "Intentional blocker", is_intentional: true }),
        painPoint({ id: "pp-closed", title: "Closed blocker", status: "closed" }),
      ],
      [
        scoringSummary({ pain_point_id: "pp-block", is_blocker: true, blocker_labels: ["Pilot"], counted: 1, score: scoreValue({ raw: 10 }) }),
        scoringSummary({ pain_point_id: "pp-fine", counted: 1, score: scoreValue({ raw: 2 }) }),
        scoringSummary({ pain_point_id: "pp-int", is_blocker: true, blocker_labels: ["Pilot"], counted: 1, score: scoreValue({ raw: 10 }) }),
        scoringSummary({ pain_point_id: "pp-closed", is_blocker: true, blocker_labels: ["Pilot"], counted: 1, score: scoreValue({ raw: 10 }) }),
      ],
    ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Blocking problem")).toBeInTheDocument());
    // Open, not intentional, and a Blocker: only the first survives.
    await expect(canvas.queryByText("Fine problem")).not.toBeInTheDocument();
    await expect(canvas.queryByText("Intentional blocker")).not.toBeInTheDocument();
    await expect(canvas.queryByText("Closed blocker")).not.toBeInTheDocument();
    await expect(canvas.getByRole("checkbox", { name: "Open only" })).toBeChecked();
    await expect(canvas.getByRole("checkbox", { name: "Blockers only" })).toBeChecked();
    await expect(canvas.getByRole("checkbox", { name: "Hide intentional limitations" })).toBeChecked();
    // The seeded filters are ordinary controls: clearing one widens the list.
    await userEvent.click(canvas.getByRole("checkbox", { name: "Blockers only" }));
    await expect(canvas.getByText("Fine problem")).toBeInTheDocument();
  },
};

/** `intentional=only` and `scored=no` seed the other direction of the same controls. */
export const OpensWithOnlyIntentionalAndUnscored: Story = {
  parameters: { query: "?intentional=only&scored=no&status=submitted" },
  beforeEach: () =>
    mockPageApis(
      [
        painPoint({ id: "pp-a", title: "Intentional unscored", is_intentional: true }),
        painPoint({ id: "pp-b", title: "Intentional scored", is_intentional: true }),
        painPoint({ id: "pp-c", title: "Ordinary unscored" }),
      ],
      [scoringSummary({ pain_point_id: "pp-b", counted: 1, score: scoreValue({ raw: 4 }) })],
    ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Intentional unscored")).toBeInTheDocument());
    await expect(canvas.queryByText("Intentional scored")).not.toBeInTheDocument();
    await expect(canvas.queryByText("Ordinary unscored")).not.toBeInTheDocument();
    await expect(canvas.getByRole("checkbox", { name: "Only intentional limitations" })).toBeChecked();
  },
};

/** An unknown value in the URL is ignored rather than breaking the page or filtering everything out. */
export const IgnoresUnknownFilterValues: Story = {
  parameters: { query: "?status=bogus&priority=nope&scored=maybe&rollup=wat" },
  beforeEach: () => mockPageApis([painPoint({ title: "Still listed" })]),
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByText("Still listed")).toBeInTheDocument());
  },
};

/** Export and Import are on the title row; Export carries the page's filters (the server applies the same rules). */
export const ExportCarriesThePageFilters: Story = {
  parameters: { query: "?status=triaged&intentional=hide&q=pric" },
  beforeEach: () => {
    mockPageApis([painPoint({ title: "Competitive pricing pressure", status: "triaged" })]);
    spyOn(api, "getForBlob").mockResolvedValue(new Blob(["code\n"], { type: "text/csv" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Competitive pricing pressure")).toBeInTheDocument());
    await expect((await openListMenu(canvas)).getByRole("menuitem", { name: "Import from CSV" })).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    await chooseExport(canvas, "CSV");
    await waitFor(() => expect(api.getForBlob).toHaveBeenCalledWith("/api/v1/projects/project-1/records/pain_point/export?status=triaged&search=pric&hide_intentional=true"));
  },
};


/** A person who may score gets a Grid view of the same filters; a change saves through the row endpoint. */
export const ScorerEditsScoresInTheGrid: Story = {
  beforeEach: () => {
    mockPageApis([painPoint()], [], { canScore: true });
    spyOn(api, "patch").mockImplementation(async (_path: string, body?: unknown) => {
      const { cells } = body as { cells: Record<string, string> };
      return { ...buildGrid().rows[0], cells: { ...buildGrid().rows[0].cells, ...cells } };
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Grid view" }));
    await canvas.findByRole("table", { name: "Pain points grid" });
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(expect.stringMatching(/\/records\/pain_point\/grid\?.*open_only=true/)));
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Severity for PNP-001" }), "Blocker");
    await userEvent.click(canvas.getByRole("button", { name: "Save 1 change" }));
    await waitFor(() =>
      expect(api.patch).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT_ID}/records/pain_point/rows/PNP-001`, { cells: { severity: "Blocker" }, expected: { severity: "" } },
      ),
    );
    await expect(await within(document.body).findByText("1 saved.")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "List view" }));
    await canvas.findByRole("table", { name: "Pain Points" });
  },
};

/** Someone who cannot score is offered no Grid view. */
export const NoGridViewWithoutTheScoringGrant: Story = {
  beforeEach: () => mockPageApis([painPoint()], [], { canScore: false }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("table", { name: "Pain Points" });
    await expect(canvas.queryByRole("button", { name: "Grid view" })).not.toBeInTheDocument();
  },
};
