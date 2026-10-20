import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import type { CollectedLink } from "../api/artefactLinks";
import { buildLinksApi, LINKS_PROJECT_ID } from "../testing/artefactLinksFixtures";
import { withToast } from "../testing/storybook-helpers";
import { useCommitQuickLinks } from "./useCommitQuickLinks";

const LINK: CollectedLink = {
  link_type_id: "lt-related", direction: "outgoing", other_type: "decision", other_id: "dec-1",
  phrase: "Related to", otherLabel: "DEC-001 Use Postgres", otherTypeLabel: "Decision",
};

/** Commits the given links against a new record and shows the outcome the caller sees. */
function Harness({ api, links }: { api: ReturnType<typeof buildLinksApi>; links: CollectedLink[] }) {
  const commit = useCommitQuickLinks(LINKS_PROJECT_ID, "pain_point", api);
  const [outcome, setOutcome] = useState("");
  return (
    <div>
      <button onClick={async () => setOutcome((await commit("pain-new", links)) ? "linked" : "failed")}>Commit</button>
      <output>{outcome}</output>
    </div>
  );
}

/** Creates the links a create form collected, after the record exists, and reports the outcome in a toast. */
const meta: Meta<typeof Harness> = {
  title: "Hooks/useCommitQuickLinks",
  component: Harness,
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof Harness>;

export const CreatesAllTheLinksInOneCall: Story = {
  args: { api: buildLinksApi(), links: [LINK, { ...LINK, other_id: "dec-2" }] },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Commit" }));
    await waitFor(() => expect(within(document.body).getByText("Linked to 2 records.")).toBeInTheDocument());
    await expect(args.api.createMany).toHaveBeenCalledTimes(1);
    await expect(args.api.createMany).toHaveBeenCalledWith(LINKS_PROJECT_ID, "pain_point", "pain-new", [
      { link_type_id: "lt-related", direction: "outgoing", other_type: "decision", other_id: "dec-1" },
      { link_type_id: "lt-related", direction: "outgoing", other_type: "decision", other_id: "dec-2" },
    ]);
    await expect(canvasElement.querySelector("output")).toHaveTextContent("linked");
  },
};

export const NothingChosenMakesNoCall: Story = {
  args: { api: buildLinksApi(), links: [] },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Commit" }));
    await waitFor(() => expect(canvasElement.querySelector("output")).toHaveTextContent("linked"));
    await expect(args.api.createMany).not.toHaveBeenCalled();
  },
};

/** The record is already saved, so a refusal is explained and points at the Links panel rather than undoing anything. */
export const AFailureNamesTheLinkAndPointsAtTheLinksPanel: Story = {
  args: {
    api: buildLinksApi({ createMany: fn(async () => { throw new Error("Link 2 of 2: These records are already linked this way."); }) }),
    links: [LINK, { ...LINK, other_id: "dec-2" }],
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Commit" }));
    await waitFor(() => expect(within(document.body).getByText(/The record was saved, but its links were not added: Link 2 of 2/)).toBeInTheDocument());
    await expect(within(document.body).getByText(/Add them from its Links panel\./)).toBeInTheDocument();
    await expect(canvasElement.querySelector("output")).toHaveTextContent("failed");
  },
};
