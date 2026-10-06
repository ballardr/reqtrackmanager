import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api, ApiError } from "../api/client";
import {
  linkTypesFor,
  type ArtefactLinkRule,
  type ArtefactTypeOption,
  type LinkTypeDefinition,
  type LinkTypeUsage,
  type ProjectArtefactLinkRule,
  type ProjectCustomisation,
  type ProjectLinkType,
  type ProjectLinkTypes,
} from "../api/types";
import { buildLinkType, buildProjectLinkType, withToast } from "../testing/storybook-helpers";
import { LinkTypesPanel } from "./LinkTypesPanel";

const ORG = "org-1";
const PROJECT = "proj-1";

const artefactTypes: ArtefactTypeOption[] = [
  { type: "requirement", label: "Requirement" },
  { type: "decision", label: "Decision" },
  { type: "pain_point", label: "Pain point" },
];

const defaultLinkTypes: LinkTypeDefinition[] = [
  buildLinkType({ id: "lt-depends", forward_name: "Depends on", reverse_name: "Is a dependency of", flow: "forward_is_upstream" }),
  buildLinkType({ id: "lt-related", forward_name: "Related to", reverse_name: "Related to" }),
  buildLinkType({
    id: "lt-addresses", forward_name: "Addresses", reverse_name: "Is addressed by", flow: "forward_is_upstream",
    allowed_source_types: ["decision"], allowed_target_types: ["pain_point"],
  }),
  buildLinkType({ id: "lt-supersedes", forward_name: "Supersedes", reverse_name: "Is superseded by", dedicated_endpoint: true }),
];

const defaultRules: ArtefactLinkRule[] = artefactTypes.map((a) => ({
  artefact_type: a.type, label: a.label, link_type_ids: null,
}));

const usage: LinkTypeUsage = {
  link_count: 12, project_count: 2, pending_change_requests: 0, approved_requirement_links: 3,
  rule_artefact_types: [{ type: "requirement", label: "Requirement" }], emptied_rule_artefact_types: [],
  is_dedicated: false, is_last: false,
  moved_link_count: 12, keep_available: false, keep_project_count: null, unmanageable_project_count: 0,
  candidates: [
    { id: "lt-related", forward_name: "Related to", reverse_name: "Related to", flow: "none", compatible: true, reason: null, flow_differs: true },
    {
      id: "lt-addresses", forward_name: "Addresses", reverse_name: "Is addressed by", flow: "forward_is_upstream",
      compatible: false, reason: "It cannot start from a requirement, which some links do.", flow_differs: false,
    },
  ],
};

const customisation: ProjectCustomisation = { locks: [], local_link_type_count: 3, local_link_type_project_count: 2 };

function mockApis(overrides: { linkTypes?: LinkTypeDefinition[]; rules?: ArtefactLinkRule[]; usage?: LinkTypeUsage; customisation?: ProjectCustomisation } = {}) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.includes("/usage")) return overrides.usage ?? usage;
    if (path.endsWith("/project-customisation")) return overrides.customisation ?? customisation;
    if (path.endsWith("/artefact-types")) return artefactTypes;
    if (path.endsWith("/artefact-link-rules")) return overrides.rules ?? defaultRules;
    if (path.endsWith("/link-types")) return overrides.linkTypes ?? defaultLinkTypes;
    throw new Error(`unmocked GET ${path}`);
  });
  spyOn(api, "patch").mockResolvedValue(undefined);
}

const meta: Meta<typeof LinkTypesPanel> = {
  title: "Components/LinkTypesPanel",
  component: LinkTypesPanel,
  decorators: [withToast()],
  args: { scope: { kind: "organization", orgId: ORG } },
};
export default meta;

type Story = StoryObj<typeof LinkTypesPanel>;

const body = () => within(document.body);

/** Each link type shows which kinds of record it may join as artefact-type
 * labels (never raw keys), "Any artefact" when unrestricted, and a note instead
 * of the pickers for a type with its own action. */
export const ShowsRestrictionsAsLabels: Story = {
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByDisplayValue("Addresses")).toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "Can link from: Addresses" })).toHaveTextContent("Decision");
    await expect(canvas.getByRole("button", { name: "Can link to: Addresses" })).toHaveTextContent("Pain point");
    await expect(canvas.getByRole("button", { name: "Can link from: Depends on" })).toHaveTextContent("Any artefact");
    await expect(canvas.getByText(/Made with its own action/)).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Can link from: Supersedes" })).not.toBeInTheDocument();
  },
};

/** Ticking a kind of record saves the restriction at once and confirms with a
 * Toast; unticking the last one clears it back to "any". */
export const SettingAndClearingARestriction: Story = {
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByDisplayValue("Depends on")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Can link from: Depends on" }));
    await userEvent.click(body().getByRole("checkbox", { name: "Can link from: Depends on: Requirement" }));
    await waitFor(() =>
      expect(api.patch).toHaveBeenCalledWith(`/api/v1/orgs/${ORG}/link-types/lt-depends`, {
        forward_name: "Depends on", reverse_name: "Is a dependency of", allowed_source_types: ["requirement"],
      })
    );
    await expect(await body().findByText("Link type restriction updated.")).toBeInTheDocument();

    // Clearing the only ticked kind on "Addresses" (target: Pain point) sends null, i.e. any.
    await userEvent.keyboard("{Escape}");
    await userEvent.click(canvas.getByRole("button", { name: "Can link to: Addresses" }));
    await userEvent.click(body().getByRole("checkbox", { name: "Can link to: Addresses: Pain point" }));
    await waitFor(() =>
      expect(api.patch).toHaveBeenCalledWith(`/api/v1/orgs/${ORG}/link-types/lt-addresses`, {
        forward_name: "Addresses", reverse_name: "Is addressed by", allowed_target_types: null,
      })
    );
  },
};

/** A type that is in use opens the in-use dialog with what depends on it, the
 * replacements that fit, those that don't (with the reason), and a caution when
 * a replacement's direction differs; moving reports what happened in a Toast. */
export const DeletingAnInUseTypeMovesItsLinks: Story = {
  beforeEach: () => {
    mockApis();
    spyOn(api, "delete").mockImplementation(async (path: string) => {
      if (path.includes("mode=reassign")) return { moved: 11, merged: 1, removed: 0, copies_created: 0, copies_renamed: [] };
      throw new ApiError(409, "This link type is used by 12 link(s).");
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByDisplayValue("Depends on")).toBeInTheDocument());
    const row = canvas.getByDisplayValue("Depends on").closest<HTMLElement>(".stack")!;
    await userEvent.click(within(row).getByTitle("Delete this link type"));

    const dialog = within(await body().findByRole("dialog", { name: "Delete “Depends on”?" }));
    await expect(dialog.getByText("12 link(s) in 2 project(s) use this link type.")).toBeInTheDocument();
    await expect(dialog.getByText(/3 of the links involve an approved requirement/)).toBeInTheDocument();
    await expect(dialog.getByText(/named in the link rule of: Requirement/)).toBeInTheDocument();
    await expect(dialog.getByRole("option", { name: /Addresses \(cannot be used: It cannot start from a requirement/ })).toBeDisabled();

    await userEvent.selectOptions(dialog.getByRole("combobox", { name: "Reassign existing items to" }), "Related to");
    await expect(dialog.getByRole("status")).toHaveTextContent("Its direction differs");
    await userEvent.click(dialog.getByRole("button", { name: "Confirm delete" }));

    await waitFor(() =>
      expect(api.delete).toHaveBeenCalledWith(`/api/v1/orgs/${ORG}/link-types/lt-depends?mode=reassign&reassign_to_id=lt-related`)
    );
    await expect(await body().findByText("Link type deleted: 11 link(s) moved, 1 merged.")).toBeInTheDocument();
  },
};

/** Deleting the links too is Tier 2 (type the name) and blocked, with the reason
 * shown, while pending change requests propose the type. */
export const RemovingLinksIsTier2AndCanBeBlocked: Story = {
  beforeEach: () => {
    mockApis();
    spyOn(api, "delete").mockImplementation(async (path: string) => {
      if (path.includes("mode=remove_links")) return { moved: 0, merged: 0, removed: 12, copies_created: 0, copies_renamed: [] };
      throw new ApiError(409, "This link type is used by 12 link(s).");
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByDisplayValue("Depends on")).toBeInTheDocument());
    const row = canvas.getByDisplayValue("Depends on").closest<HTMLElement>(".stack")!;
    await userEvent.click(within(row).getByTitle("Delete this link type"));

    const dialog = within(await body().findByRole("dialog", { name: "Delete “Depends on”?" }));
    await userEvent.click(dialog.getByRole("button", { name: "Delete the links too…" }));
    const confirm = body().getByRole("button", { name: "Delete links and link type" });
    await expect(confirm).toBeDisabled();
    await userEvent.type(body().getByLabelText('Type "Depends on" to confirm'), "Depends on");
    await userEvent.click(confirm);
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`/api/v1/orgs/${ORG}/link-types/lt-depends?mode=remove_links`));
    await expect(await body().findByText("Link type deleted: 12 link(s) deleted.")).toBeInTheDocument();
  },
};

export const RemovingLinksBlockedByPendingChangeRequests: Story = {
  beforeEach: () => {
    mockApis({ usage: { ...usage, pending_change_requests: 2 } });
    spyOn(api, "delete").mockRejectedValue(new ApiError(409, "This link type is used by 12 link(s)."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByDisplayValue("Depends on")).toBeInTheDocument());
    const row = canvas.getByDisplayValue("Depends on").closest<HTMLElement>(".stack")!;
    await userEvent.click(within(row).getByTitle("Delete this link type"));
    const dialog = within(await body().findByRole("dialog"));
    await expect(dialog.getByRole("button", { name: "Delete the links too…" })).toBeDisabled();
    await expect(dialog.getAllByText(/2 pending change request\(s\) propose this link type/).length).toBeGreaterThan(0);
  },
};

/** The second tab lists the artefact-type rules. */
export const ByArtefactTypeTab: Story = {
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByDisplayValue("Depends on")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("tab", { name: "By artefact type" }));
    await expect(await canvas.findByRole("button", { name: "Link types allowed for Pain point" })).toBeInTheDocument();
    await expect(canvas.queryByDisplayValue("Depends on")).not.toBeInTheDocument();
  },
};

/** Pickers offer only link types that may join the pair: restricted ones that exclude it, and types with
 * their own action, are left out (the server still enforces the rules). */
export const PickersOfferOnlyUsableLinkTypes: Story = {
  render: () => <div>Usable link types</div>,
  play: async () => {
    const names = (source: string, target: string) => linkTypesFor(defaultLinkTypes, source, target).map((t) => t.forward_name);
    await expect(names("requirement", "requirement")).toEqual(["Depends on", "Related to"]);
    await expect(names("decision", "pain_point")).toEqual(["Depends on", "Related to", "Addresses"]);
    await expect(names("decision", "requirement")).toEqual(["Depends on", "Related to"]);
  },
};


// --- organisation scope: the switch forbidding project-level link types ----------------------------

/** Projects may customise by default; switching it off asks first (Tier 1), stating how many project-level
 * types stop applying, saves the lock, and confirms with a Toast. Nothing is deleted. */
export const OrganisationCanForbidProjectLinkTypes: Story = {
  beforeEach: () => {
    mockApis();
    spyOn(api, "put").mockResolvedValue({});
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const toggle = await canvas.findByRole("switch", { name: "Let projects add their own link types and hide the organisation's" });
    await expect(toggle).toBeChecked();
    await expect(canvas.getByText("3 project-level link type(s) in 2 project(s) are affected.")).toBeInTheDocument();

    await userEvent.click(toggle);
    const dialog = within(await body().findByRole("dialog", { name: "Switch off project link types?" }));
    await expect(dialog.getByText(/3 project-level link type\(s\) in 2 project\(s\).*Nothing is deleted/)).toBeInTheDocument();
    await userEvent.click(dialog.getByRole("button", { name: "Switch off" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(`/api/v1/orgs/${ORG}/project-customisation`, { locks: ["link_types"] }));
    await expect(await body().findByText("Project customisation updated.")).toBeInTheDocument();
  },
};

// --- project scope -------------------------------------------------------------------------------

const projectRelated = buildProjectLinkType({ id: "lt-related", forward_name: "Related to", reverse_name: "Related to" });
const projectInherited = buildProjectLinkType({
  id: "lt-parent", forward_name: "Parent verb", reverse_name: "Parent reverse", scope: "inherited",
  owner_project_id: "proj-parent", owner_project_name: "Platform",
});
const projectOwn = buildProjectLinkType({
  id: "lt-own", forward_name: "Own verb", reverse_name: "Own reverse", scope: "project", owner_project_id: PROJECT, editable: true,
});

function mockProjectApis(
  items: ProjectLinkType[],
  options: { locked?: boolean; rules?: ProjectArtefactLinkRule[]; usageFor?: (path: string) => LinkTypeUsage } = {},
) {
  const payload: ProjectLinkTypes = { locked: options.locked ?? false, items };
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.includes("/usage")) return options.usageFor ? options.usageFor(path) : usage;
    if (path.endsWith(`/projects/${PROJECT}/link-types`)) return payload;
    if (path.endsWith("/artefact-types")) return artefactTypes;
    if (path.endsWith(`/projects/${PROJECT}/artefact-link-rules`)) {
      return options.rules ?? artefactTypes.map((a) => ({ artefact_type: a.type, label: a.label, link_type_ids: null, source: null, source_project_name: null, own: false }));
    }
    throw new Error(`unmocked GET ${path}`);
  });
  spyOn(api, "put").mockResolvedValue({});
  spyOn(api, "patch").mockResolvedValue(undefined);
  spyOn(api, "delete").mockResolvedValue(undefined);
}

const projectScope = { kind: "project", orgId: ORG, projectId: PROJECT } as const;

/** A project sees the organisation's and its parents' types read-only, each saying where it comes from,
 * above its own types in the same editable row the organisation's use. */
export const ProjectShowsInheritedAboveItsOwn: Story = {
  args: { scope: projectScope },
  beforeEach: () => mockProjectApis([projectRelated, projectInherited, projectOwn]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const available = within(await canvas.findByRole("region", { name: "Available to this project" }));
    await expect(available.getByText("Related to", { selector: "strong" })).toBeInTheDocument();
    await expect(available.getByText("Organisation")).toBeInTheDocument();
    await expect(available.getByText("Inherited from Platform")).toBeInTheDocument();
    await expect(available.queryByDisplayValue("Own verb")).not.toBeInTheDocument();

    const own = within(canvas.getByRole("region", { name: "Link types of this project" }));
    await expect(own.getByDisplayValue("Own verb")).toBeInTheDocument();
    await expect(own.getByRole("button", { name: "Can link from: Own verb" })).toHaveTextContent("Any artefact");
  },
};

/** Hiding an organisation type is one click with a Toast; it only removes it from pickers. */
export const ProjectHidesAnOrganisationType: Story = {
  args: { scope: projectScope },
  beforeEach: () => mockProjectApis([projectRelated, projectOwn]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Hide Related to in this project" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT}/link-types/lt-related/visibility`, { hidden: true }));
    await expect(await body().findByText("Link type visibility updated.")).toBeInTheDocument();
  },
};

/** A hidden type says so (and by whom), offers Show, and a type another one shadows says why it is not offered. */
export const ProjectShowsHiddenAndShadowedStates: Story = {
  args: { scope: projectScope },
  beforeEach: () =>
    mockProjectApis([
      buildProjectLinkType({ id: "lt-hidden", forward_name: "Hidden verb", hidden: true, hidden_here: true }),
      buildProjectLinkType({ id: "lt-parent-hidden", forward_name: "Parent hid this", hidden: true, hidden_by_inherited: true }),
      buildProjectLinkType({
        id: "lt-shadow", forward_name: "Same name", scope: "inherited", owner_project_id: "p", shadowed_by_scope: "organization",
        shadowed_by_name: "Same name",
      }),
    ]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Show Hidden verb in this project" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT}/link-types/lt-hidden/visibility`, { hidden: false }));
    await expect(canvas.getByText("Hidden by a parent project")).toBeInTheDocument();
    await expect(canvas.getByText("Not offered: “Same name” takes precedence")).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: /Same name in this project/ })).not.toBeInTheDocument();
  },
};

/** While the organisation locks customisation the project view is read-only: the organisation's types only,
 * no Hide/Show, no add row, and the reason stated. */
export const ProjectLockedByOrganisationIsReadOnly: Story = {
  args: { scope: projectScope },
  beforeEach: () => mockProjectApis([projectRelated], { locked: true }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("Your organisation uses one shared set of link types, so they cannot be changed here.")).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: /Hide Related to/ })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "New link type" })).not.toBeInTheDocument();
  },
};

/** The project's rule view names where each rule comes from and lets the project replace or drop its own. */
export const ProjectRulesNameTheirSource: Story = {
  args: { scope: projectScope },
  beforeEach: () =>
    mockProjectApis([projectRelated, projectOwn], {
      rules: [
        { artefact_type: "requirement", label: "Requirement", link_type_ids: ["lt-related"], source: "organization", source_project_name: null, own: false },
        { artefact_type: "decision", label: "Decision", link_type_ids: ["lt-own"], source: "project", source_project_name: null, own: true },
        { artefact_type: "pain_point", label: "Pain point", link_type_ids: ["lt-related"], source: "inherited", source_project_name: "Platform", own: false },
      ],
    }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("tab", { name: "By artefact type" }));
    await expect(await canvas.findByText("Organisation rule")).toBeInTheDocument();
    await expect(canvas.getByText("Inherited from Platform")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Use inherited rule" }));
    const dialog = within(await body().findByRole("dialog", { name: "Use the inherited rule for Decision?" }));
    await userEvent.click(dialog.getByRole("button", { name: "Use inherited rule" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT}/artefact-link-rules/decision`));
  },
};

// --- deleting a type other projects use -----------------------------------------------------------

const keepUsage: LinkTypeUsage = { ...usage, keep_available: true, keep_project_count: 2, moved_link_count: 4 };

/** For a type other projects use, the dialog offers (ticked) to keep it for them as copies; moving the
 * rest then says so to the server and the Toast reports the copies. */
export const KeepingATypeForOtherProjectsIsOfferedAndSent: Story = {
  args: { scope: projectScope },
  beforeEach: () => {
    mockProjectApis([projectRelated, projectOwn], { usageFor: (path) => (path.includes("keep_in_projects=true") ? keepUsage : usage) });
    spyOn(api, "delete").mockImplementation(async (path: string) => {
      if (path.includes("mode=reassign")) return { moved: 4, merged: 0, removed: 0, copies_created: 2, copies_renamed: ["Own verb (copy)"] };
      throw new ApiError(409, "This link type is used by 12 link(s).");
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByDisplayValue("Own verb")).toBeInTheDocument());
    const row = canvas.getByDisplayValue("Own verb").closest<HTMLElement>(".stack")!;
    await userEvent.click(within(row).getByTitle("Delete this link type"));

    const dialog = within(await body().findByRole("dialog", { name: "Delete “Own verb”?" }));
    const keep = await dialog.findByRole("checkbox", { name: "Keep this link type in the 2 other project(s) that use it" });
    await expect(keep).toBeChecked();
    await userEvent.selectOptions(dialog.getByRole("combobox", { name: "Reassign existing items to" }), "Related to");
    await userEvent.click(dialog.getByRole("button", { name: "Confirm delete" }));
    await waitFor(() =>
      expect(api.delete).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT}/link-types/lt-own?mode=reassign&reassign_to_id=lt-related&keep_in_projects=true`)
    );
    await expect(
      await body().findByText("Link type deleted: 4 link(s) moved; kept in 2 project(s); renamed to avoid a clash: Own verb (copy).")
    ).toBeInTheDocument();
  },
};

/** When keeping leaves nothing else to move, the dialog offers a plain delete instead of the move/remove choices. */
export const KeepingEverythingOffersAPlainDelete: Story = {
  args: { scope: projectScope },
  beforeEach: () => {
    mockProjectApis([projectRelated, projectOwn], { usageFor: () => ({ ...keepUsage, moved_link_count: 0 }) });
    spyOn(api, "delete").mockImplementation(async (path: string) => {
      if (path.includes("keep_in_projects=true")) return { moved: 0, merged: 0, removed: 0, copies_created: 2, copies_renamed: [] };
      throw new ApiError(409, "This link type is used by 4 link(s).");
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByDisplayValue("Own verb")).toBeInTheDocument());
    const row = canvas.getByDisplayValue("Own verb").closest<HTMLElement>(".stack")!;
    await userEvent.click(within(row).getByTitle("Delete this link type"));
    const dialog = within(await body().findByRole("dialog", { name: "Delete “Own verb”?" }));
    await expect(dialog.queryByRole("combobox", { name: "Reassign existing items to" })).not.toBeInTheDocument();
    await userEvent.click(await dialog.findByRole("button", { name: "Delete and keep it for the other projects" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT}/link-types/lt-own?keep_in_projects=true`));
    await expect(await body().findByText("Link type deleted: kept in 2 project(s).")).toBeInTheDocument();
  },
};

/** Unticking keep reassesses against every link, and links in projects the caller cannot manage block moving,
 * with a count and no project names. */
export const UnticksKeepAndMovingIsBlockedForUnmanageableProjects: Story = {
  args: { scope: projectScope },
  beforeEach: () => {
    mockProjectApis([projectRelated, projectOwn], {
      usageFor: (path) =>
        path.includes("keep_in_projects=true") ? keepUsage : { ...keepUsage, moved_link_count: 12, unmanageable_project_count: 2 },
    });
    spyOn(api, "delete").mockRejectedValue(new ApiError(409, "This link type is used by 12 link(s)."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByDisplayValue("Own verb")).toBeInTheDocument());
    const row = canvas.getByDisplayValue("Own verb").closest<HTMLElement>(".stack")!;
    await userEvent.click(within(row).getByTitle("Delete this link type"));
    const dialog = within(await body().findByRole("dialog", { name: "Delete “Own verb”?" }));
    await userEvent.click(await dialog.findByRole("checkbox", { name: "Keep this link type in the 2 other project(s) that use it" }));
    await waitFor(() => expect(dialog.getAllByText(/2 other project\(s\) hold links of this type that you cannot manage/).length).toBeGreaterThan(0));
    await expect(dialog.getByRole("button", { name: "Confirm delete" })).toBeDisabled();
    await expect(dialog.getByRole("button", { name: "Delete the links too…" })).toBeDisabled();
  },
};
