import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import type { ArtefactLinkFinderParams } from "../api/artefactLinks";
import {
  buildBrowseStep, buildCandidate, buildGraph, buildGraphNode, buildLinksApi, buildOption, buildRelatedProject,
  LINKS_ARTEFACT_ID, LINKS_PROJECT_ID,
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
    await dialog.findByRole("option", { name: "DEC-002 Use Redis" });
    // The relationship is chosen after the record, from those usable for it; "Related to" is the default.
    await expect(dialog.queryByLabelText("Relationship")).not.toBeInTheDocument();
    await userEvent.selectOptions(dialog.getByLabelText("Record"), "dec-2");
    await waitFor(() => expect(dialog.getByLabelText("Relationship")).toHaveValue("lt-related:outgoing"));
    await userEvent.selectOptions(dialog.getByLabelText("Relationship"), "lt-impl:incoming");
    await userEvent.click(dialog.getByRole("button", { name: "Add link" }));
    await waitFor(() =>
      expect(args.api!.create).toHaveBeenCalledWith(LINKS_PROJECT_ID, "requirement", LINKS_ARTEFACT_ID, {
        link_type_id: "lt-impl", direction: "incoming", other_type: "decision", other_id: "dec-2", other_project_id: undefined,
      }),
    );
    await waitFor(() => expect(args.onChanged).toHaveBeenCalled());
  },
};

/** The finder searches every record type from two characters and labels each result with its type. */
export const SearchesEveryRecordTypeFromTwoCharacters: Story = {
  args: {
    api: buildLinksApi({
      candidates: fn(async (_p: string, _t: string, _i: string, params: ArtefactLinkFinderParams) => ({
        items: params.otherType === undefined && params.query === "re"
          ? [buildCandidate(), buildCandidate({ type: "pain_point", type_label: "Pain Point", id: "pp-9", label: "Reports are slow" })]
          : [],
        truncated: false,
      })),
    }),
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Add link" }));
    const dialog = within(await within(document.body).findByRole("dialog"));
    // Nothing is searched until a type is chosen or two characters are typed.
    await expect(await dialog.findByText(/Type at least two characters to search every record type/)).toBeInTheDocument();
    await expect(args.api!.candidates).not.toHaveBeenCalled();
    await userEvent.type(dialog.getByLabelText("Search"), "r");
    await expect(args.api!.candidates).not.toHaveBeenCalled();
    await userEvent.type(dialog.getByLabelText("Search"), "e");
    await dialog.findByRole("option", { name: "Decision: DEC-002 Use Redis" });
    await expect(dialog.getByRole("option", { name: "Pain Point: Reports are slow" })).toBeInTheDocument();
    await expect(args.api!.candidates).toHaveBeenLastCalledWith(LINKS_PROJECT_ID, "requirement", LINKS_ARTEFACT_ID, {
      otherType: undefined, otherProjectId: undefined, selected: undefined, query: "re",
    });
    // Picking a result offers only the relationships usable for its type.
    await userEvent.selectOptions(dialog.getByLabelText("Record"), "pp-9");
    await waitFor(() => expect(dialog.getByLabelText("Relationship")).toHaveValue("lt-related:outgoing"));
  },
};

/** A type's browse levels narrow the search step by step; changing an earlier level resets the later ones. */
export const NarrowsATypeByItsBrowseLevels: Story = {
  args: {
    api: buildLinksApi({
      options: fn(async () => [buildOption({ other_types: [{ type: "compliance_requirement", label: "Compliance standard clause" }] })]),
      browse: fn(async (_p: string, _t: string, _i: string, params: ArtefactLinkFinderParams) => {
        const chosen = params.selected ?? [];
        if (chosen.length === 0) {
          return buildBrowseStep({
            key: "standard", label: "Standard",
            options: [{ id: "std-1", label: "ISO-27001 Information security" }, { id: "std-2", label: "SOC-2 Trust services" }],
          });
        }
        if (chosen.length === 1) {
          return buildBrowseStep({
            key: "version", label: "Version",
            options: [{ id: `ver-${chosen[0][1]}`, label: "v2.0" }],
          });
        }
        return null;
      }),
      candidates: fn(async () => ({
        items: [buildCandidate({
          type: "compliance_requirement", type_label: "Compliance standard clause", id: "clause-1",
          label: "ISO-27001 v2.0 · A.5.15 Logical access control", project_id: null,
        })],
        truncated: false,
      })),
    }),
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Add link" }));
    const dialog = within(await within(document.body).findByRole("dialog"));
    // One type is offered, so it is preselected and its first level appears.
    await userEvent.selectOptions(await dialog.findByLabelText("Standard"), "std-1");
    await userEvent.selectOptions(await dialog.findByLabelText("Version"), "ver-std-1");
    await waitFor(() =>
      expect(args.api!.candidates).toHaveBeenLastCalledWith(LINKS_PROJECT_ID, "requirement", LINKS_ARTEFACT_ID, {
        otherType: "compliance_requirement", otherProjectId: undefined,
        selected: [["standard", "std-1"], ["version", "ver-std-1"]], query: undefined,
      }),
    );
    // Changing the standard drops the version choice and offers the new standard's versions.
    await userEvent.selectOptions(dialog.getByLabelText("Standard"), "std-2");
    await waitFor(() => expect(dialog.getByLabelText("Version")).toHaveValue(""));
    await expect(within(dialog.getByLabelText("Version")).getByRole("option", { name: "v2.0" })).toHaveValue("ver-std-2");
    // Back to "Any standard" removes the later level altogether.
    await userEvent.selectOptions(dialog.getByLabelText("Standard"), "");
    await waitFor(() => expect(dialog.queryByLabelText("Version")).not.toBeInTheDocument());
    // The record is chosen from the narrowed results; the relationship follows.
    await userEvent.selectOptions(dialog.getByLabelText("Record"), "clause-1");
    await waitFor(() => expect(dialog.getByLabelText("Relationship")).toHaveValue("lt-related:outgoing"));
    await userEvent.click(dialog.getByRole("button", { name: "Add link" }));
    await waitFor(() =>
      expect(args.api!.create).toHaveBeenCalledWith(LINKS_PROJECT_ID, "requirement", LINKS_ARTEFACT_ID, {
        link_type_id: "lt-related", direction: "outgoing", other_type: "compliance_requirement", other_id: "clause-1",
        other_project_id: undefined,
      }),
    );
  },
};

/** A long level offers its own filter so a long list (all standards, all components) is itself searchable. */
export const FiltersALongBrowseLevel: Story = {
  args: {
    api: buildLinksApi({
      options: fn(async () => [buildOption({ other_types: [{ type: "requirement", label: "Requirement" }] })]),
      browse: fn(async (_p: string, _t: string, _i: string, params: ArtefactLinkFinderParams) =>
        buildBrowseStep({
          key: "component", label: "Component", truncated: true,
          options: params.query ? [{ id: "c-7", label: "Navigation unit" }] : [{ id: "c-1", label: "Airframe" }],
        })),
    }),
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Add link" }));
    const dialog = within(await within(document.body).findByRole("dialog"));
    await userEvent.type(await dialog.findByLabelText("Filter component options"), "nav");
    await dialog.findByRole("option", { name: "Navigation unit" });
    await expect(args.api!.browse).toHaveBeenLastCalledWith(
      LINKS_PROJECT_ID, "requirement", LINKS_ARTEFACT_ID,
      expect.objectContaining({ otherType: "requirement", query: "nav" }),
    );
    await expect(dialog.getByText(/Only the first options are shown/)).toBeInTheDocument();
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
