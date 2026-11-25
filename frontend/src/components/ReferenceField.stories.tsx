import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { DRAFT_ARTEFACT_ID } from "../api/artefactLinks";
import { takePendingReferences } from "../hooks/pendingReferences";
import { buildRecordReferences, buildReferencesApi, REFERENCES_PROJECT_ID } from "../testing/referencesFixtures";
import { ReferenceField } from "./ReferenceField";

/**
 * The "External references" field of a create form. It asks about a record that does not exist yet, holds the references
 * for `useCommitTags` to add once the record is saved, and shows nothing when the caller may not change references of
 * this kind of record, the project offers no system or the read fails.
 */
const meta: Meta<typeof ReferenceField> = {
  title: "Components/ReferenceField",
  component: ReferenceField,
  args: { projectId: REFERENCES_PROJECT_ID, artefactType: "pain_point" },
};
export default meta;

type Story = StoryObj<typeof ReferenceField>;

export const AddingReferencesForANewRecord: Story = {
  args: { api: buildReferencesApi(buildRecordReferences({ references: [] })) },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Add a reference" }));
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Reference 1 system" }), "Jira");
    await userEvent.type(canvas.getByRole("textbox", { name: "Reference 1 key" }), "PROJ-5");
    await userEvent.click(canvas.getByRole("button", { name: "Add a reference" }));
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Reference 2 system" }), "DOORS");
    await expect(args.api!.get).toHaveBeenCalledWith(REFERENCES_PROJECT_ID, "pain_point", DRAFT_ARTEFACT_ID);
    // A half-filled row (no key or link yet) is not handed to the commit step; the complete one is.
    await expect(takePendingReferences(REFERENCES_PROJECT_ID, "pain_point")).toEqual([
      { system_id: "s-jira", key: "PROJ-5", url: null, note: "", role: null },
    ]);
    await userEvent.type(canvas.getByRole("textbox", { name: "Reference 2 key" }), "REQ-2");
    await userEvent.click(canvas.getByRole("button", { name: "Remove reference 1" }));
    await expect(takePendingReferences(REFERENCES_PROJECT_ID, "pain_point")).toEqual([
      { system_id: "s-doors", key: "REQ-2", url: null, note: "", role: null },
    ]);
  },
};

export const HiddenWhenTheCallerCannotChangeReferencesOfThisType: Story = {
  args: { api: buildReferencesApi(buildRecordReferences({ can_edit: false, references: [] })) },
  play: async ({ canvasElement, args }) => {
    await waitFor(() => expect(args.api!.get).toHaveBeenCalled());
    await expect(within(canvasElement).queryByRole("button", { name: "Add a reference" })).not.toBeInTheDocument();
  },
};

export const HiddenWhenTheProjectOffersNoSystem: Story = {
  args: { api: buildReferencesApi(buildRecordReferences({ references: [], systems: [] })) },
  play: async ({ canvasElement, args }) => {
    await waitFor(() => expect(args.api!.get).toHaveBeenCalled());
    await expect(within(canvasElement).queryByRole("button", { name: "Add a reference" })).not.toBeInTheDocument();
  },
};

export const HiddenWhenTheReadFails: Story = {
  args: { api: buildReferencesApi(undefined, { get: fn(async () => { throw new Error("404"); }) }) },
  play: async ({ canvasElement, args }) => {
    await waitFor(() => expect(args.api!.get).toHaveBeenCalled());
    await expect(within(canvasElement).queryByRole("button", { name: "Add a reference" })).not.toBeInTheDocument();
  },
};
