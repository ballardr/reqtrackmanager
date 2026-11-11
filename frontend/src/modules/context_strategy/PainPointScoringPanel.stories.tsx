import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { buildPainPointScheme, painPointScores, scoreEntry, scoreValue } from "./painPointScoringFixtures";
import { PainPointScoringPanel } from "./PainPointScoringPanel";
import type { PainPointScores } from "./types";

const PROJECT_ID = "project-1";
const PAIN_POINT_ID = "pain-point-1";
const SCORES_PATH = `/api/v1/projects/${PROJECT_ID}/modules/context_strategy/pain-points/${PAIN_POINT_ID}/scores`;

/** Serves the scheme and the given scores; the model query param is echoed back. */
function mockScoring(scores: PainPointScores) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === `/api/v1/projects/${PROJECT_ID}/scoring-schemes/pain_point`) return buildPainPointScheme();
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
    scoreEntry({
      target_id: null, target_type: null, label: null, weight: null, status: "general",
      levels: { severity: "sev-3", frequency: "freq-2", job_size: "size-1" }, effective_levels: { severity: "sev-3", frequency: "freq-2", job_size: "size-1" },
      score: scoreValue({ raw: 6, band_label: "Medium", band_tone: "info" }),
    }),
    scoreEntry({
      target_id: "persona-2", label: "Back-office Planner", weight: 1, levels: { severity: "sev-5" },
      effective_levels: { severity: "sev-5", frequency: "freq-2", job_size: "size-1" },
      score: scoreValue({ raw: 10, band_label: "Critical", band_tone: "danger" }), is_blocker: true,
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
    const general = within(canvas.getByRole("group", { name: "General scores" }));
    await expect(general.getByRole("combobox", { name: "Severity" })).toHaveValue("");
    await expect(general.getByRole("combobox", { name: "Job size" })).toHaveValue("");
    await expect(canvas.getByRole("combobox", { name: "Add a persona that differs" })).toBeInTheDocument();
  },
};

export const PerPersonaShowsRollupAndBlocker: Story = {
  beforeEach: () => mockScoring(PER_PERSONA),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("group", { name: "Back-office Planner scores" }));
    const rollup = within(canvas.getByRole("group", { name: "Rolled-up score" }));
    await expect(rollup.getByText("Critical · 14")).toBeInTheDocument();
    await expect(rollup.getByText("Blocker")).toHaveAttribute("title", "Unusable for: Back-office Planner");
    const planner = within(canvas.getByRole("group", { name: "Back-office Planner scores" }));
    await expect(planner.getByRole("combobox", { name: "Severity" })).toHaveValue("sev-5");
    // A criterion scored for the whole Pain Point is set under General only.
    await expect(planner.queryByRole("combobox", { name: "Job size" })).not.toBeInTheDocument();
    await expect(within(canvas.getByRole("group", { name: "General scores" })).getByRole("combobox", { name: "Job size" })).toHaveValue("size-1");
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
      painPointScores({ scope: "general", counted: 1, entries: [scoreEntry({ target_id: null, target_type: null, label: null, weight: null, status: "general" })] }),
    );
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("group", { name: "General scores" }));
    const row = within(canvas.getByRole("group", { name: "General scores" }));
    await userEvent.selectOptions(row.getByRole("combobox", { name: "Severity" }), "sev-4");
    await userEvent.selectOptions(row.getByRole("combobox", { name: "Frequency" }), "freq-4");
    await userEvent.selectOptions(row.getByRole("combobox", { name: "Job size" }), "size-2");
    await userEvent.click(canvas.getByRole("button", { name: "Save scores" }));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith(
        expect.stringContaining(SCORES_PATH),
        { scores: [{ target_id: null, levels: { severity: "sev-4", frequency: "freq-4", job_size: "size-2" } }] },
      ),
    );
    await waitFor(() => expect(within(document.body).getByText("Scores saved.")).toBeInTheDocument());
  },
};

/** A persona is added only where it differs from General, and holds the per-persona criteria only. */
export const AddingAPersonaOffersOnlyPerPersonaCriteria: Story = {
  beforeEach: () => mockScoring(painPointScores()),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("combobox", { name: "Add a persona that differs" }));
    await expect(canvas.queryByRole("group", { name: "Field Technician scores" })).not.toBeInTheDocument();
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Add a persona that differs" }), "persona-1");
    const technician = within(canvas.getByRole("group", { name: "Field Technician scores" }));
    await expect(technician.getByRole("combobox", { name: "Severity" })).toHaveValue("");
    await expect(technician.queryByRole("combobox", { name: "Job size" })).not.toBeInTheDocument();
    // The added persona is no longer offered, and can be removed again.
    await expect(within(canvas.getByRole("combobox", { name: "Add a persona that differs" })).queryByRole("option", { name: "Field Technician" })).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Remove Field Technician scores" }));
    await expect(canvas.queryByRole("group", { name: "Field Technician scores" })).not.toBeInTheDocument();
  },
};

/** The save sends the General row and each persona that differs. */
export const SavesGeneralAndPersonaRows: Story = {
  beforeEach: () => {
    mockScoring(painPointScores());
    spyOn(api, "put").mockResolvedValue(painPointScores());
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("combobox", { name: "Add a persona that differs" }));
    await userEvent.selectOptions(within(canvas.getByRole("group", { name: "General scores" })).getByRole("combobox", { name: "Severity" }), "sev-2");
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Add a persona that differs" }), "persona-2");
    await userEvent.selectOptions(within(canvas.getByRole("group", { name: "Back-office Planner scores" })).getByRole("combobox", { name: "Severity" }), "sev-5");
    await userEvent.click(canvas.getByRole("button", { name: "Save scores" }));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith(expect.stringContaining(SCORES_PATH), {
        scores: [
          { target_id: null, levels: { severity: "sev-2" } },
          { target_id: "persona-2", levels: { severity: "sev-5" } },
        ],
      }),
    );
  },
};
