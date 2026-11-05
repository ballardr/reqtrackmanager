import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { ApiError } from "../api/client";
import type { ScoringCriteriaCalls, ScoringScheme } from "../api/scoring";
import { buildCustomCriteriaScheme, buildScoringScheme, withToast } from "../testing/storybook-helpers";
import { ScoringCriteria } from "./ScoringCriteria";

/** Calls that resolve with `result` unless overridden; each is a spy the play function checks. */
function calls(result: ScoringScheme, overrides: Partial<ScoringCriteriaCalls> = {}): ScoringCriteriaCalls {
  const ok = () => Promise.resolve(result);
  return {
    setEnabledModels: fn(ok), createAxis: fn(ok), updateAxis: fn(ok), deleteAxis: fn(ok), createModel: fn(ok),
    updateModel: fn(ok), deleteModel: fn(ok), hideCriterion: fn(ok), restoreCriterion: fn(ok), ...overrides,
  } as ScoringCriteriaCalls;
}

/** Holds the scheme the way the editors do, so a result of a call is shown. */
function Harness(props: { scheme: ScoringScheme; calls: ScoringCriteriaCalls; projectId?: string }) {
  const [scheme, setScheme] = useState(props.scheme);
  return <ScoringCriteria scheme={scheme} calls={props.calls} projectId={props.projectId} onChange={setScheme} />;
}

const meta: Meta<typeof Harness> = {
  title: "Components/Scoring/ScoringCriteria",
  component: Harness,
  decorators: [withToast()],
  args: { scheme: buildCustomCriteriaScheme(), calls: calls(buildCustomCriteriaScheme()) },
};
export default meta;

type Story = StoryObj<typeof Harness>;

const body = () => within(document.body);
const dialog = () => within(body().getByRole("dialog"));

/** The organisation edits its own criteria and can only hide the built-in ones. */
export const OwnCriteriaAreEditableAndBuiltInsOnlyHideable: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Edit Strategic fit" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Delete Strategic fit" })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Edit Impact" })).not.toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Hide Impact" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Hide ICE" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Edit Weighted value" })).toBeInTheDocument();
    await expect(canvas.getByText("Worked out from demand")).toBeInTheDocument();
  },
};

/** A scheme that takes no custom criteria shows nothing. */
export const HiddenWhenTheSchemeTakesNone: Story = {
  args: { scheme: buildScoringScheme() },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("heading", { name: "Criteria" })).not.toBeInTheDocument();
  },
};

/** A project sees the organisation's criteria as another tier's: hide only. Its own are editable. */
export const ProjectOwnsOnlyItsOwn: Story = {
  args: {
    projectId: "project-1",
    scheme: (() => {
      const s = buildCustomCriteriaScheme();
      return { ...s, axes: [...s.axes, { key: "c_local", label: "Local fit", description: null, origin: "project" as const, owner_project_id: "project-1", levels: s.axes[2].levels }] };
    })(),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Hide Strategic fit" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Edit Local fit" })).toBeInTheDocument();
    await expect(canvas.getByText("This project")).toBeInTheDocument();
  },
};

export const AddAxis: Story = {
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Add axis" }));
    const d = dialog();
    await userEvent.type(d.getByLabelText("Name"), "Risk");
    await userEvent.type(d.getByLabelText("Level 1 name"), "Low");
    await userEvent.type(d.getByLabelText("Level 1 weight"), "1");
    await userEvent.type(d.getByLabelText("Level 2 name"), "High");
    await userEvent.type(d.getByLabelText("Level 2 weight"), "2");
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.calls.createAxis).toHaveBeenCalledWith({
      label: "Risk", description: null,
      levels: [{ name: "Low", weight: 1, description: null }, { name: "High", weight: 2, description: null }],
    }));
    await waitFor(() => expect(body().getByText("Axis added.")).toBeInTheDocument());
    await expect(body().queryByRole("dialog")).not.toBeInTheDocument();
  },
};

/** A failed save stays in the dialog with the server's reason. */
export const SaveErrorStaysInTheDialog: Story = {
  args: { calls: calls(buildCustomCriteriaScheme(), { updateAxis: fn(() => Promise.reject(new ApiError(400, "An axis with this name already exists here."))) }) },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Edit Strategic fit" }));
    const d = dialog();
    await userEvent.clear(d.getByLabelText("Name"));
    await userEvent.type(d.getByLabelText("Name"), "Impact");
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(d.getByText("An axis with this name already exists here.")).toBeInTheDocument());
  },
};

export const AddModel: Story = {
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Add model" }));
    const d = dialog();
    await userEvent.type(d.getByLabelText("Name"), "Fit first");
    await userEvent.selectOptions(d.getByLabelText("Strategic fit role"), "multiply");
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.calls.createModel).toHaveBeenCalledWith({
      label: "Fit first", combination: "product", axes: [{ axis_key: "c_strategic_fit", role: "multiply", exponent: 1 }],
    }));
    await waitFor(() => expect(body().getByText("Model added.")).toBeInTheDocument());
  },
};

/** Hiding asks first, says it is reversible, then calls the hide endpoint. */
export const HideAsksFirst: Story = {
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Hide Impact" }));
    const d = dialog();
    await expect(d.getByText(/you can restore it from the Hidden list/)).toBeInTheDocument();
    await userEvent.click(d.getByRole("button", { name: "Hide" }));
    await waitFor(() => expect(args.calls.hideCriterion).toHaveBeenCalledWith({ kind: "axis", key: "impact" }));
    await waitFor(() => expect(body().getByText("Impact hidden.")).toBeInTheDocument());
  },
};

export const RestoreAHiddenCriterion: Story = {
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Restore RICE" }));
    await waitFor(() => expect(args.calls.restoreCriterion).toHaveBeenCalledWith({ kind: "model", key: "rice" }));
    await waitFor(() => expect(body().getByText("RICE restored.")).toBeInTheDocument());
  },
};

/** An axis with stored scores asks twice: delete, then again to drop those scores. */
export const DeleteAxisWithScoresAsksToDropThem: Story = {
  args: {
    calls: (() => {
      const deleteAxis = fn((_key: string, clearScores?: boolean) => clearScores
        ? Promise.resolve(buildCustomCriteriaScheme())
        : Promise.reject(new ApiError(409, "3 score(s) use this axis; delete it with clear_scores to drop them.")));
      return calls(buildCustomCriteriaScheme(), { deleteAxis });
    })(),
  },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Delete Strategic fit" }));
    await userEvent.click(dialog().getByRole("button", { name: "Delete axis" }));
    await waitFor(() => expect(dialog().getByText(/3 score\(s\) use this axis\. Deleting the axis removes those scores/)).toBeInTheDocument());
    await userEvent.click(dialog().getByRole("button", { name: "Delete axis and scores" }));
    await waitFor(() => expect(args.calls.deleteAxis).toHaveBeenLastCalledWith("c_strategic_fit", true));
    await waitFor(() => expect(body().getByText("Axis deleted.")).toBeInTheDocument());
  },
};

/** An axis a model still uses cannot go; the server's reason is shown. */
export const DeleteAxisUsedByAModelShowsWhy: Story = {
  args: { calls: calls(buildCustomCriteriaScheme(), { deleteAxis: fn(() => Promise.reject(new ApiError(409, "Model(s) still use this axis: Weighted value."))) }) },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Delete Strategic fit" }));
    await userEvent.click(dialog().getByRole("button", { name: "Delete axis" }));
    await waitFor(() => expect(body().getByText("Model(s) still use this axis: Weighted value.")).toBeInTheDocument());
  },
};

export const DeleteModelAsksFirst: Story = {
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Delete Weighted value" }));
    await userEvent.click(dialog().getByRole("button", { name: "Delete model" }));
    await waitFor(() => expect(args.calls.deleteModel).toHaveBeenCalledWith("m_weighted_value"));
    await waitFor(() => expect(body().getByText("Model deleted.")).toBeInTheDocument());
  },
};
