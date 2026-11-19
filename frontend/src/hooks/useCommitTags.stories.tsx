import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import type { RecordReferencesApi } from "../api/externalReferences";
import type { RecordTagsApi } from "../api/tags";
import { buildReferencesApi } from "../testing/referencesFixtures";
import { withToast } from "../testing/storybook-helpers";
import { buildRecordTagsApi, TAGS_PROJECT_ID } from "../testing/tagsFixtures";
import { setPendingReferences } from "./pendingReferences";
import { useCommitTags } from "./useCommitTags";

/** Commits the given tags against a new record and shows the outcome the caller sees. */
function Harness({ api, names, referencesApi }: { api: RecordTagsApi; names: string[]; referencesApi?: RecordReferencesApi }) {
  const commit = useCommitTags(TAGS_PROJECT_ID, "pain_point", api, undefined, referencesApi);
  const [outcome, setOutcome] = useState("");
  return (
    <div>
      <button onClick={async () => setOutcome((await commit("pain-new", names)) ? "tagged" : "failed")}>Commit</button>
      <output>{outcome}</output>
    </div>
  );
}

/** Applies the tags, components and external references a create form collected, after the record exists; a refusal never undoes the record. */
const meta: Meta<typeof Harness> = {
  title: "Hooks/useCommitTags",
  component: Harness,
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof Harness>;

export const SavesTheWholeSetInOneCall: Story = {
  args: { api: buildRecordTagsApi(), names: ["Safety", "Security"] },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Commit" }));
    await waitFor(() => expect(canvasElement.querySelector("output")).toHaveTextContent("tagged"));
    await expect(args.api.set).toHaveBeenCalledWith(TAGS_PROJECT_ID, "pain_point", "pain-new", ["Safety", "Security"]);
  },
};

export const NothingToDoMakesNoCall: Story = {
  args: { api: buildRecordTagsApi(), names: [] },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Commit" }));
    await waitFor(() => expect(canvasElement.querySelector("output")).toHaveTextContent("tagged"));
    await expect(args.api.set).not.toHaveBeenCalled();
  },
};

/** A refusal is reported in a toast that says where to add the tags by hand. */
export const ARefusalIsReportedAndNeverThrows: Story = {
  args: {
    api: buildRecordTagsApi(undefined, { set: fn(async () => { throw new Error("'Nope' is not in the tag list."); }) }),
    names: ["Nope"],
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Commit" }));
    await waitFor(() => expect(canvasElement.querySelector("output")).toHaveTextContent("failed"));
    await expect(await within(document.body).findByText(/The record was saved, but its tags were not added: 'Nope' is not in the tag list\./)).toBeInTheDocument();
  },
};

/** The references the create form collected are added one by one once the record exists. */
export const AddsTheCollectedReferences: Story = {
  args: { api: buildRecordTagsApi(), names: [], referencesApi: buildReferencesApi() },
  play: async ({ canvasElement, args }) => {
    setPendingReferences(TAGS_PROJECT_ID, "pain_point", [
      { system_id: "s-jira", key: "PROJ-1", url: null, note: "", role: null },
      { system_id: "s-doors", key: "REQ-2", url: null, note: "", role: "origin" },
    ]);
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Commit" }));
    await waitFor(() => expect(canvasElement.querySelector("output")).toHaveTextContent("tagged"));
    await expect(args.referencesApi!.add).toHaveBeenCalledTimes(2);
    await expect(args.referencesApi!.add).toHaveBeenCalledWith(TAGS_PROJECT_ID, "pain_point", "pain-new", { system_id: "s-doors", key: "REQ-2", url: null, note: "", role: "origin" });
  },
};

/** A refused reference is reported in a toast; the record and the other references stay. */
export const ARefusedReferenceIsReportedAndNeverThrows: Story = {
  args: {
    api: buildRecordTagsApi(), names: [],
    referencesApi: buildReferencesApi(undefined, { add: fn(async () => { throw new Error("A record can have at most 50 references."); }) }),
  },
  play: async ({ canvasElement }) => {
    setPendingReferences(TAGS_PROJECT_ID, "pain_point", [{ system_id: "s-jira", key: "PROJ-1", url: null, note: "", role: null }]);
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Commit" }));
    await waitFor(() => expect(canvasElement.querySelector("output")).toHaveTextContent("failed"));
    await expect(await within(document.body).findByText(/The record was saved, but a reference was not added: A record can have at most 50 references\./)).toBeInTheDocument();
  },
};
