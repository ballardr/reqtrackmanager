import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildProject, buildScoringScheme, withRouter, withToast } from "../../testing/storybook-helpers";
import { scoreValue, scoringSummary } from "./painPointScoringFixtures";
import { ProjectPainPointsPage } from "./ProjectPainPointsPage";
import type { EffectivePainPointType, PainPoint, PainPointScoringSummary } from "./types";

const PROJECT_ID = "project-1";

const TYPES: EffectivePainPointType[] = [
  { id: "type-operator", name: "Operator", display_order: 0, is_enabled: true, source: "org" },
];

function painPoint(overrides: Partial<PainPoint> = {}): PainPoint {
  return {
    id: "pain-point-1", project_id: PROJECT_ID, pain_point_type_id: "type-operator", pain_point_type_name: "Operator",
    creator_id: "user-1", is_archived: false, archived_at: null, archived_by: null,
    title: "Report delays under poor connectivity", description: "Field reports queue for days.",
    source: "Operator interviews", impact: "Decisions are made on stale data.", evidence: "12 reports last month.",
    priority: "high", status: "submitted", owner_id: null, date_identified: "2026-01-05", is_intentional: false, is_locked: false,
    created_at: "2026-01-05T09:00:00Z", updated_at: "2026-01-05T09:00:00Z",
    ...overrides,
  };
}

function mockPageApis(painPoints: PainPoint[], scoring: PainPointScoringSummary[] = []) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
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
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof ProjectPainPointsPage>;

export const ListsPainPoints: Story = {
  beforeEach: () => mockPageApis([painPoint(), painPoint({ id: "pain-point-2", title: "Competitive pricing pressure", status: "rejected" })]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Report delays under poor connectivity")).toBeInTheDocument());
    await expect(canvas.getByText("Competitive pricing pressure")).toBeInTheDocument();
  },
};

/** Score and Blocker columns render the roll-up; the Score column sorts unscored last. */
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
    await expect(canvas.getByText("Blocker")).toBeInTheDocument();
    await expect(canvas.getByText("Intentional")).toBeInTheDocument();
    // Scoped to the table: the Scoring filter's "Not scored" option has the same text.
    await expect(within(canvas.getByRole("table", { name: "Pain Points" })).getByText("Not scored")).toBeInTheDocument();

    const titles = () => canvas.getAllByRole("button", { name: /problem/ }).map((b) => b.textContent?.replace("Intentional", ""));
    const scoreHeader = canvas.getByRole("button", { name: /Score/ });
    await userEvent.click(scoreHeader); // ascending
    await waitFor(() => expect(titles()).toEqual(["Low scoring problem", "High scoring problem", "Unscored problem"]));
    await userEvent.click(scoreHeader); // descending: unscored still last
    await waitFor(() => expect(titles()).toEqual(["High scoring problem", "Low scoring problem", "Unscored problem"]));
  },
};

/** The model switcher refetches the roll-up under the newly chosen model. */
export const SwitchingModelRefetchesScores: Story = {
  beforeEach: () => mockPageApis([painPoint()]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("combobox", { name: "Scoring model" }));
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Scoring model" }), "sxf");
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(expect.stringContaining("model_key=sxf")));
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
