import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { DRAFT_ARTEFACT_ID, type CollectedLink } from "../api/artefactLinks";
import { buildCandidate, buildGraph, buildLinksApi, buildOption, buildRelatedProject, LINKS_PROJECT_ID } from "../testing/artefactLinksFixtures";
import { buildUser, withRouter, withStatefulAuth, withToast } from "../testing/storybook-helpers";
import { ProposedLinksEditor } from "./ProposedLinksEditor";

const COLLECTED: CollectedLink = {
  link_type_id: "lt-related", direction: "outgoing", other_type: "decision", other_id: "dec-1",
  phrase: "Related to", otherLabel: "DEC-001 Use Postgres", otherTypeLabel: "Decision",
};

/** Holds the collected links in state, as the change request form does. */
function Harness({ initial = [], ...rest }: Omit<React.ComponentProps<typeof ProposedLinksEditor>, "links" | "onChange"> & { initial?: CollectedLink[] }) {
  const [links, setLinks] = useState<CollectedLink[]>(initial);
  return <ProposedLinksEditor {...rest} links={links} onChange={setLinks} />;
}

/**
 * The "Proposed links" section of the form that drafts a new or modify-requirement change
 * request (docs/plans/platform-enhancements-2026-10-plan.md Phase 6b). It collects links; the
 * form sends them with the request and creates nothing here.
 */
const meta: Meta<typeof Harness> = {
  title: "Components/ProposedLinksEditor",
  component: Harness,
  decorators: [withToast(), withRouter("/"), withStatefulAuth(buildUser())],
  args: { projectId: LINKS_PROJECT_ID, artefactId: "requirement-1" },
};
export default meta;

type Story = StoryObj<typeof Harness>;

export const EmptyAndOffersToAddALink: Story = {
  args: { api: buildLinksApi({ graph: fn(async () => buildGraph([], { can_link: true })) }) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("No links proposed.")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Add a link" })).toBeInTheDocument();
  },
};

/** Choosing a record in the dialog adds it to the list; nothing is created, so `create` is never called. */
export const CollectsALinkWithoutCreatingIt: Story = {
  args: {
    api: buildLinksApi({
      options: fn(async () => [buildOption({ other_types: [{ type: "decision", label: "Decision" }] })]),
    }),
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Add a link" }));
    const dialog = within(await within(document.body).findByRole("dialog"));
    await dialog.findByRole("option", { name: "DEC-002 Use Redis" });
    await userEvent.selectOptions(dialog.getByLabelText("Record"), "dec-2");
    await userEvent.click(dialog.getByRole("button", { name: "Add to the request" }));
    await waitFor(() => expect(canvas.getByText("DEC-002 Use Redis")).toBeInTheDocument());
    await expect(canvas.getByText("Related to")).toBeInTheDocument();
    await expect(args.api!.create).not.toHaveBeenCalled();
    await expect(canvas.queryByText("No links proposed.")).not.toBeInTheDocument();
  },
};

export const RemovesACollectedLink: Story = {
  args: { initial: [COLLECTED], api: buildLinksApi() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Remove proposed link: Related to DEC-001 Use Postgres" }));
    await expect(canvas.getByText("No links proposed.")).toBeInTheDocument();
  },
};

/** A record in a parent or child project carries the project badge, like a link in the Links panel. */
export const ShowsTheProjectOfALinkedRecordElsewhere: Story = {
  args: { initial: [{ ...COLLECTED, otherProjectLabel: "Programme", other_project_id: "project-parent" }], api: buildLinksApi() },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("In Programme")).toBeInTheDocument();
  },
};

export const OffersTheProjectChoiceForAParentOrChild: Story = {
  args: {
    api: buildLinksApi({
      projects: fn(async () => ({ items: [buildRelatedProject()], truncated: false })),
      candidates: fn(async () => ({ items: [buildCandidate()], truncated: false })),
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Add a link" }));
    const dialog = within(await within(document.body).findByRole("dialog"));
    await expect(await dialog.findByLabelText("Project")).toBeInTheDocument();
    await expect(dialog.getByRole("option", { name: "Parent: Programme" })).toBeInTheDocument();
  },
};

/** For a request that creates the requirement, the finder is asked about the draft id. */
export const SearchesAsADraftRequirementForANewRequest: Story = {
  args: { artefactId: DRAFT_ARTEFACT_ID, api: buildLinksApi() },
  play: async ({ canvasElement, args }) => {
    await within(canvasElement).findByRole("button", { name: "Add a link" });
    await expect(args.api!.options).toHaveBeenCalledWith(LINKS_PROJECT_ID, "requirement", DRAFT_ARTEFACT_ID);
    await expect(args.api!.graph).not.toHaveBeenCalled();
  },
};

/** Someone who may not link requirements is not offered the section at all. */
/** A stakeholder cannot link an approved requirement directly, but may propose links on a request for it. */
export const OfferedToSomeoneWhoMayOnlyPropose: Story = {
  args: { api: buildLinksApi({ graph: fn(async () => buildGraph([], { can_link: false, can_propose: true })) }) },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByRole("button", { name: "Add a link" })).toBeInTheDocument();
  },
};

export const HiddenWhenTheUserCannotLink: Story = {
  args: { api: buildLinksApi({ graph: fn(async () => buildGraph([], { can_link: false, can_propose: false })) }) },
  play: async ({ canvasElement, args }) => {
    await waitFor(() => expect(args.api!.graph).toHaveBeenCalled());
    await expect(within(canvasElement).queryByRole("button", { name: "Add a link" })).not.toBeInTheDocument();
  },
};

export const HiddenWhenTheFinderRefusesADraft: Story = {
  args: {
    artefactId: DRAFT_ARTEFACT_ID,
    api: buildLinksApi({ options: fn(async () => { throw new Error("403"); }) }),
  },
  play: async ({ canvasElement, args }) => {
    await waitFor(() => expect(args.api!.options).toHaveBeenCalled());
    await expect(within(canvasElement).queryByRole("button", { name: "Add a link" })).not.toBeInTheDocument();
  },
};
