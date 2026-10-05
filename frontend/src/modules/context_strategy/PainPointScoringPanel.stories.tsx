import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildScoringScheme, withToast } from "../../testing/storybook-helpers";
import { painPointScores, scoreEntry, scoreValue } from "./painPointScoringFixtures";
import { PainPointScoringPanel } from "./PainPointScoringPanel";
import type { PainPointScores } from "./types";

const PROJECT_ID = "project-1";
const PAIN_POINT_ID = "pain-point-1";
const SCORES_PATH = `/api/v1/projects/${PROJECT_ID}/modules/context_strategy/pain-points/${PAIN_POINT_ID}/scores`;

/** Serves the scheme and the given scores; the model query param is echoed back. */
function mockScoring(scores: PainPointScores) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === `/api/v1/projects/${PROJECT_ID}/scoring-schemes/pain_point`) return buildScoringScheme();
    if (path.startsWith(SCORES_PATH)) {
      const model = new URL(path, "http://localhost").searchParams.get("model_key");
      return model ? { ...scores, model_key: model, model_source: "chosen" } : scores;
    }
    throw new Error(`Unmocked GET: ${path}`);
  });
}

const PER_PERSONA = painPointScores({
  scope: "per_persona", counted: 2, is_blocker: true, blocker_labels: ["Back-office Planner"], score: scoreValue({ raw: 14, band_label: "Critical", band_tone: "danger" }),
  entries: [
    scoreEntry(),
    scoreEntry({
      target_id: "persona-2", label: "Back-office Planner", weight: 1, severity_level_id: "sev-5", frequency_level_id: "freq-1",
      score: scoreValue({ raw: 5, band_label: "Medium", band_tone: "info" }), is_blocker: true,
    }),
  ],
});

const meta: Meta<typeof PainPointScoringPanel> = {
  title: "Modules/ContextStrategy/PainPointScoringPanel",
  component: PainPointScoringPanel,
  args: { projectId: PROJECT_ID, painPointId: PAIN_POINT_ID, locked: false },
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof PainPointScoringPanel>;

export const NotScoredYet: Story = {
  beforeEach: () => mockScoring(painPointScores()),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Not scored yet.")).toBeInTheDocument());
    await expect(canvas.getByRole("combobox", { name: "Scoring mode" })).toHaveValue("all");
    await expect(within(canvas.getByRole("group", { name: "All personas scores" })).getByRole("combobox", { name: "Severity" })).toHaveValue("");
  },
};

export const PerPersonaShowsRollupAndBlocker: Story = {
  beforeEach: () => mockScoring(PER_PERSONA),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("combobox", { name: "Scoring mode" })).toHaveValue("persona"));
    const rollup = within(canvas.getByRole("group", { name: "Rolled-up score" }));
    await expect(rollup.getByText("Critical · 14")).toBeInTheDocument();
    await expect(rollup.getByText("Blocker")).toHaveAttribute("title", "Unusable for: Back-office Planner");
    const planner = within(canvas.getByRole("group", { name: "Back-office Planner scores" }));
    await expect(planner.getByRole("combobox", { name: "Severity" })).toHaveValue("sev-5");
  },
};

/** Changing the model or the persona roll-up asks the backend to re-roll-up. */
export const SwitchingModelRecalculates: Story = {
  beforeEach: () => mockScoring(PER_PERSONA),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("combobox", { name: "Scoring model" }));
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Scoring model" }), "sxf");
    await waitFor(() =>
      expect(api.get).toHaveBeenCalledWith(expect.stringContaining("model_key=sxf")),
    );
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Combine personas by" }), "worst_case");
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(expect.stringContaining("rollup=worst_case")));
  },
};

export const SavesChosenLevels: Story = {
  beforeEach: () => {
    mockScoring(painPointScores());
    spyOn(api, "put").mockResolvedValue(
      painPointScores({ scope: "all_personas", counted: 1, entries: [scoreEntry({ target_id: null, target_type: null, label: null, weight: null, status: "all" })] }),
    );
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("group", { name: "All personas scores" }));
    const row = within(canvas.getByRole("group", { name: "All personas scores" }));
    await userEvent.selectOptions(row.getByRole("combobox", { name: "Severity" }), "sev-4");
    await userEvent.selectOptions(row.getByRole("combobox", { name: "Frequency" }), "freq-4");
    await userEvent.click(canvas.getByRole("button", { name: "Save scores" }));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith(
        expect.stringContaining(SCORES_PATH),
        { scores: [{ target_id: null, severity_level_id: "sev-4", frequency_level_id: "freq-4", confidence_level_id: null }] },
      ),
    );
    await waitFor(() => expect(within(document.body).getByText("Scores saved.")).toBeInTheDocument());
  },
};

export const SwitchingToEachPersonaListsPersonas: Story = {
  beforeEach: () => mockScoring(painPointScores()),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("combobox", { name: "Scoring mode" }));
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Scoring mode" }), "persona");
    await expect(canvas.getByRole("group", { name: "Field Technician scores" })).toBeInTheDocument();
    await expect(canvas.getByRole("group", { name: "Back-office Planner scores" })).toBeInTheDocument();
    await expect(canvas.getByText("weight 3")).toBeInTheDocument();
  },
};

export const NoPersonasOnlyOffersAllPersonas: Story = {
  beforeEach: () => mockScoring(painPointScores({ available_targets: [] })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText(/Personas aren't available in this project/)).toBeInTheDocument());
    await expect(canvas.queryByRole("combobox", { name: "Scoring mode" })).not.toBeInTheDocument();
  },
};

export const UnavailablePersonaIsKeptAndExplained: Story = {
  beforeEach: () =>
    mockScoring(painPointScores({
      scope: "per_persona", counted: 1, personas_degraded: true, available_targets: [],
      entries: [scoreEntry({ target_id: "gone", label: null, weight: null, status: "unavailable" })],
    })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText(/no longer available/)).toBeInTheDocument());
    await expect(canvas.getByRole("group", { name: "Persona unavailable scores" })).toBeInTheDocument();
  },
};

export const LockedDisablesEditing: Story = {
  args: { locked: true },
  beforeEach: () => mockScoring(PER_PERSONA),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Save scores" }));
    await expect(canvas.getByRole("button", { name: "Save scores" })).toBeDisabled();
    await expect(canvas.getByRole("combobox", { name: "Scoring mode" })).toBeDisabled();
    await expect(canvas.getByText(/terminal outcome/)).toBeInTheDocument();
  },
};

export const DarkTheme: Story = { ...PerPersonaShowsRollupAndBlocker, globals: { theme: "dark" } };
