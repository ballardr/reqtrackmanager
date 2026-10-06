import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api, ApiError } from "../api/client";
import { linkTypesFor, type ArtefactLinkRule, type ArtefactTypeOption, type LinkTypeDefinition, type LinkTypeUsage } from "../api/types";
import { buildLinkType, withToast } from "../testing/storybook-helpers";
import { LinkTypesPanel } from "./LinkTypesPanel";

const ORG = "org-1";

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
  candidates: [
    { id: "lt-related", forward_name: "Related to", reverse_name: "Related to", flow: "none", compatible: true, reason: null, flow_differs: true },
    {
      id: "lt-addresses", forward_name: "Addresses", reverse_name: "Is addressed by", flow: "forward_is_upstream",
      compatible: false, reason: "It cannot start from a requirement, which some links do.", flow_differs: false,
    },
  ],
};

function mockApis(overrides: { linkTypes?: LinkTypeDefinition[]; rules?: ArtefactLinkRule[]; usage?: LinkTypeUsage } = {}) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.endsWith("/usage")) return overrides.usage ?? usage;
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
  args: { orgId: ORG },
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
      if (path.includes("mode=reassign")) return { moved: 11, merged: 1, removed: 0 };
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
    await expect(await body().findByText("Link type deleted: 11 link(s) moved, 1 merged into existing links.")).toBeInTheDocument();
  },
};

/** Deleting the links too is Tier 2 (type the name) and blocked, with the reason
 * shown, while pending change requests propose the type. */
export const RemovingLinksIsTier2AndCanBeBlocked: Story = {
  beforeEach: () => {
    mockApis();
    spyOn(api, "delete").mockImplementation(async (path: string) => {
      if (path.includes("mode=remove_links")) return { moved: 0, merged: 0, removed: 12 };
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
    await expect(await body().findByText("Link type deleted along with 12 link(s).")).toBeInTheDocument();
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

