import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import {
  buildCandidate, buildGraph, buildGraphNode, buildLinksApi, buildOption, buildRelatedProject, LINKS_ARTEFACT_ID,
  LINKS_PROJECT_ID,
} from "../testing/artefactLinksFixtures";
import { buildUser, withRouter, withStatefulAuth, withToast } from "../testing/storybook-helpers";
import { ArtefactLinksPanel } from "./ArtefactLinksPanel";

const DECISION = buildGraphNode();
const PAIN = buildGraphNode({
  type: "pain_point", id: "pp-1", type_label: "Pain Point", label: "Reports arrive late", status: "accepted",
});
const CHILD_REQ = buildGraphNode({
  type: "requirement", id: "req-2", type_label: "Requirement", label: "REQ-007 Handle disconnect", status: "approved",
  project_id: "project-child", project_name: "Software module",
});

/**
 * The Links panel every artefact detail page shows beside its content
 * (docs/plans/platform-enhancements-2026-10-plan.md Phase 6). All calls go through an
 * injected fake API.
 */
const meta: Meta<typeof ArtefactLinksPanel> = {
  title: "Components/ArtefactLinksPanel",
  component: ArtefactLinksPanel,
  decorators: [withToast(), withRouter("/"), withStatefulAuth(buildUser())],
  args: { projectId: LINKS_PROJECT_ID, artefactType: "requirement", artefactId: LINKS_ARTEFACT_ID },
};
export default meta;

type Story = StoryObj<typeof ArtefactLinksPanel>;

export const GroupsLinksByRecordType: Story = {
  args: {
    api: buildLinksApi({
      graph: fn(async () =>
        buildGraph([
          [DECISION],
          [PAIN, { phrase: "Is motivated by", flow: "upstream" }],
          [CHILD_REQ, { phrase: "Is refined by", cross_project: true }],
        ], { hidden_count: 2, unavailable_count: 1 })),
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("link", { name: "DEC-001 Use Postgres" })).toBeInTheDocument());
    // Type headings, phrases and label-mapped statuses (never the raw `in_review`-style value).
    await expect(canvas.getByRole("heading", { name: "Decision" })).toBeInTheDocument();
    await expect(canvas.getByRole("heading", { name: "Pain Point" })).toBeInTheDocument();
    await expect(canvas.getByText("Is implemented by")).toBeInTheDocument();
    await expect(canvas.getByText("Draft")).toBeInTheDocument();
    await expect(canvas.getByText("Accepted")).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "REQ-007 Handle disconnect" })).toHaveAttribute(
      "href", "/projects/project-child/requirements/req-2",
    );
    // A record in another project carries a badge that links to that project.
    await expect(canvas.getByRole("link", { name: "In Software module" })).toHaveAttribute("href", "/projects/project-child");
    await expect(canvas.getByText(/2 linked records are not shown/)).toBeInTheDocument();
    await expect(canvas.getByText(/1 linked record cannot be displayed/)).toBeInTheDocument();
  },
};

export const Empty: Story = {
  args: { api: buildLinksApi() },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByText("No links yet.")).toBeInTheDocument());
  },
};

export const FlagsALinkItsTypeNoLongerPermitsAndKeepsDedicatedLinksUnremovable: Story = {
  args: {
    api: buildLinksApi({
      graph: fn(async () =>
        buildGraph([
          [DECISION, { nesting_permitted: false, cross_project: true }],
          [PAIN, { phrase: "Supersedes", dedicated: true }],
        ])),
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No longer permitted by its link type")).toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: /Remove link: Is implemented by/ })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: /Remove link: Supersedes/ })).not.toBeInTheDocument();
  },
};

export const ReadOnlyWithoutManagePermission: Story = {
  args: { api: buildLinksApi({ graph: fn(async () => buildGraph([[DECISION]], { can_manage: false })) }) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("link", { name: "DEC-001 Use Postgres" })).toBeInTheDocument());
    await expect(canvas.queryByRole("button", { name: "Add link" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: /Remove link/ })).not.toBeInTheDocument();
  },
};

export const HidesStructuralLinksWhenThePageListsThemItself: Story = {
  args: {
    hideStructuralLinks: true,
    api: buildLinksApi({
      graph: fn(async () =>
        buildGraph([
          [DECISION],
          [buildGraphNode({ type: "requirement_action", id: "act-1", type_label: "Action", label: "ACT-001 Review", status: null }), {
            link_type_id: null, phrase: null, dedicated: true,
          }],
        ])),
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("link", { name: "DEC-001 Use Postgres" })).toBeInTheDocument());
    await expect(canvas.queryByRole("link", { name: "ACT-001 Review" })).not.toBeInTheDocument();
  },
};

export const OrganisationRecordShowsANoteInsteadOfControls: Story = {
  args: { projectId: undefined, api: buildLinksApi() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(/Links are managed from within a project/)).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Add link" })).not.toBeInTheDocument();
  },
};

export const ShowsPageSuppliedActionsBesideAddLink: Story = {
  args: { api: buildLinksApi(), actions: <button className="btn">Supersede another Decision</button> },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByRole("button", { name: "Supersede another Decision" })).toBeInTheDocument());
  },
};

export const RemovesALinkAfterConfirmation: Story = {
  args: { onChanged: fn(), api: buildLinksApi({ graph: fn(async () => buildGraph([[DECISION]])) }) },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Remove link: Is implemented by DEC-001 Use Postgres" }));
    const dialog = within(await within(document.body).findByRole("dialog"));
    await userEvent.click(dialog.getByRole("button", { name: "Remove link" }));
    await waitFor(() => expect(args.api!.remove).toHaveBeenCalledWith(LINKS_PROJECT_ID, "requirement", LINKS_ARTEFACT_ID, "link-dec-1"));
    await waitFor(() => expect(args.onChanged).toHaveBeenCalled());
  },
};

export const AddsALinkChoosingRecordTypeRelationshipAndRecord: Story = {
  args: {
    onChanged: fn(),
    api: buildLinksApi({
      options: fn(async () => [
        buildOption(),
        buildOption({
          link_type_id: "lt-impl", forward_name: "Implements", reverse_name: "Is implemented by", direction: "incoming",
          phrase: "Is implemented by", other_types: [{ type: "decision", label: "Decision" }],
        }),
      ]),
      candidates: fn(async (_p: string, _t: string, _i: string, params: { otherType: string }) => ({
        items: params.otherType === "decision" ? [buildCandidate()] : [buildCandidate({ type: "pain_point", id: "pp-9", label: "Slow login" })],
        truncated: false,
      })),
    }),
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Add link" }));
    const dialog = within(await within(document.body).findByRole("dialog"));
    await userEvent.selectOptions(await dialog.findByLabelText("Link to"), "decision");
    // "Related to" is the default relationship when offered.
    await waitFor(() => expect(dialog.getByLabelText("Relationship")).toHaveValue("lt-related:outgoing"));
    await userEvent.selectOptions(dialog.getByLabelText("Relationship"), "lt-impl:incoming");
    await dialog.findByRole("option", { name: "DEC-002 Use Redis" });
    await userEvent.selectOptions(dialog.getByLabelText("Record"), "dec-2");
    await userEvent.click(dialog.getByRole("button", { name: "Add link" }));
    await waitFor(() =>
      expect(args.api!.create).toHaveBeenCalledWith(LINKS_PROJECT_ID, "requirement", LINKS_ARTEFACT_ID, {
        link_type_id: "lt-impl", direction: "incoming", other_type: "decision", other_id: "dec-2", other_project_id: undefined,
      }),
    );
    await waitFor(() => expect(args.onChanged).toHaveBeenCalled());
  },
};

export const OffersAParentProjectAndSearchesIt: Story = {
  args: {
    api: buildLinksApi({
      projects: fn(async () => ({ items: [buildRelatedProject()], truncated: false })),
      options: fn(async () => [buildOption({ other_types: [{ type: "decision", label: "Decision" }] })]),
    }),
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Add link" }));
    const dialog = within(await within(document.body).findByRole("dialog"));
    await userEvent.selectOptions(await dialog.findByLabelText("Project"), "project-parent");
    await waitFor(() =>
      expect(args.api!.options).toHaveBeenLastCalledWith(LINKS_PROJECT_ID, "requirement", LINKS_ARTEFACT_ID, {
        otherProjectId: "project-parent",
      }),
    );
    await userEvent.type(await dialog.findByLabelText("Search"), "redis");
    await waitFor(() =>
      expect(args.api!.candidates).toHaveBeenLastCalledWith(LINKS_PROJECT_ID, "requirement", LINKS_ARTEFACT_ID, {
        otherType: "decision", otherProjectId: "project-parent", query: "redis",
      }),
    );
  },
};

export const ProposesThroughAChangeRequestWhenLinksAreLocked: Story = {
  args: {
    api: buildLinksApi({ graph: fn(async () => buildGraph([[CHILD_REQ]])) }),
    changeRequest: { onPropose: fn(async () => undefined), onProposeRemove: fn(async () => undefined) },
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: /Remove link: Is refined by|Remove link: Is implemented by/ }));
    const dialog = within(await within(document.body).findByRole("dialog"));
    const confirm = dialog.getByRole("button", { name: "Request removal" });
    await expect(confirm).toBeDisabled();
    await userEvent.type(dialog.getByLabelText("Reason for change"), "Obsolete");
    await userEvent.click(confirm);
    await waitFor(() => expect(args.changeRequest!.onProposeRemove).toHaveBeenCalledWith("link-req-2", "Obsolete"));
    await expect(args.api!.remove).not.toHaveBeenCalled();
  },
};
