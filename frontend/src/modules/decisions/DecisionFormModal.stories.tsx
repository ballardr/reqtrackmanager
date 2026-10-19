import type { Meta, StoryObj } from "@storybook/react-vite";
import { useEffect, useState } from "react";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import type { OrgGroup, OrgUser, ProjectGroup } from "../../api/types";
import { DecisionFormModal } from "./DecisionFormModal";
import type { Decision, DecisionTemplate, DecisionTypeDefinition } from "./types";

const DECISION_TYPES: DecisionTypeDefinition[] = [
  { id: "dt-1", project_id: "project-1", name: "Architecture", sort_order: 0 },
  { id: "dt-2", project_id: "project-1", name: "Strategy", sort_order: 1 },
];

const TEMPLATES: DecisionTemplate[] = [
  {
    id: "template-1", organization_id: "org-1", name: "Nygard (Classic ADR)", description: null,
    context_prompt: "What is the issue that we're seeing that is motivating this decision?",
    options_considered_prompt: null, chosen_option_prompt: null,
    rationale_prompt: "Why did we choose this option?", consequences_prompt: "What becomes easier or harder?",
    assumptions_prompt: null, constraints_prompt: null, sort_order: 0,
  },
];

function orgUser(id: string, name: string): OrgUser {
  return {
    user_id: id, email: `${name.split(" ")[0].toLowerCase()}@example.com`, display_name: name, is_active: true,
    is_archived: false, roles: ["member"], display_name_locked: false, last_login_at: null, is_2fa_enabled: false,
    module_roles: [], custom_roles: [],
  };
}

const ORG_USERS = [orgUser("user-1", "Alex Morgan"), orgUser("user-2", "Jordan Lee")];

const ORG_GROUPS: OrgGroup[] = [
  { id: "group-1", name: "Platform Architecture", member_user_ids: ["user-1", "user-2"], member_org_group_ids: [], idp_synced_group_name: null, granted_org_role: null },
];
const PROJECT_GROUPS: ProjectGroup[] = [
  { id: "pgroup-1", name: "Release board", roles: [], member_user_ids: ["user-2"], member_org_group_ids: [], member_source_project_ids: [] },
];

/** The pickers list the organisation's and project's groups and search users server-side. */
function mockDirectory() {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.endsWith("/orgs/org-1/groups")) return ORG_GROUPS as never;
    if (path.endsWith("/projects/project-1/groups")) return PROJECT_GROUPS as never;
    return { members: [], external: null } as never;
  });
}

/**
 * `DecisionFormModal` renders via `Modal`, which portals to `document.body`
 * (`createPortal`) — every assertion here queries `within(document.body)`,
 * not `canvasElement`, mirroring `modules/compliance/StandardFormModal
 * .stories.tsx`'s own identical convention for the same reason.
 */
const meta: Meta<typeof DecisionFormModal> = {
  title: "Modules/Decisions/DecisionFormModal",
  component: DecisionFormModal,
  args: {
    decisionTypes: DECISION_TYPES, orgUsers: ORG_USERS, organizationId: "org-1", projectId: "project-1",
    currentUserId: "user-1", onCancel: fn(), onSave: fn(),
  },
  beforeEach: mockDirectory,
};
export default meta;

type Story = StoryObj<typeof DecisionFormModal>;

export const CreateNew: Story = {
  play: async () => {
    const body = within(document.body);
    await expect(body.getByRole("heading", { name: "New decision" })).toBeInTheDocument();
    // The creator is the default owner, shown as a badge rather than a select.
    await expect(body.getByText("Alex Morgan (alex@example.com)")).toBeInTheDocument();
  },
};

export const CreateFromTemplate: Story = {
  args: { templates: TEMPLATES },
  play: async () => {
    const body = within(document.body);
    await userEvent.selectOptions(body.getByLabelText("Start from a template (optional)"), "template-1");
    await waitFor(() => expect(body.getByDisplayValue(
      "What is the issue that we're seeing that is motivating this decision?"
    )).toBeInTheDocument());
  },
};

export const SubmitsNewDecision: Story = {
  play: async ({ args }) => {
    const body = within(document.body);
    await userEvent.type(body.getByLabelText("Decision title"), "Adopt PostgreSQL");
    await userEvent.type(body.getByLabelText("Decision statement"), "Use PostgreSQL as the backing store.");
    await userEvent.click(body.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(args.onSave).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Adopt PostgreSQL", decision_statement: "Use PostgreSQL as the backing store.", owner: { type: "user", id: "user-1" }, decision_maker: null }), []
    ));
  },
};

/** An organisation group can be the owner; the form sends it as a typed principal. */
export const ChoosesAGroupOwner: Story = {
  play: async ({ args }) => {
    const body = within(document.body);
    await userEvent.type(body.getByLabelText("Decision title"), "Adopt PostgreSQL");
    await userEvent.type(body.getByLabelText("Decision statement"), "Use PostgreSQL as the backing store.");
    await userEvent.type(body.getByRole("combobox", { name: "Owner" }), "platform");
    await userEvent.click(await body.findByText("Platform Architecture"));
    await expect(body.getByText("Org group")).toBeInTheDocument();
    await userEvent.click(body.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(args.onSave).toHaveBeenCalledWith(
      expect.objectContaining({ owner: { type: "org_group", id: "group-1" } }), []
    ));
  },
};

/** A project group can be the decision maker, and the optional field can be cleared again. */
export const ChoosesAProjectGroupDecisionMaker: Story = {
  play: async ({ args }) => {
    const body = within(document.body);
    await userEvent.type(body.getByLabelText("Decision title"), "Adopt PostgreSQL");
    await userEvent.type(body.getByLabelText("Decision statement"), "Use PostgreSQL as the backing store.");
    await userEvent.type(body.getByRole("combobox", { name: "Decision maker" }), "release");
    await userEvent.click(await body.findByText("Release board"));
    await userEvent.click(body.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.onSave).toHaveBeenCalledWith(
      expect.objectContaining({ decision_maker: { type: "project_group", id: "pgroup-1" } }), []
    ));
    await userEvent.click(body.getByRole("button", { name: "Unassign: Decision maker" }));
    await userEvent.click(body.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.onSave).toHaveBeenLastCalledWith(expect.objectContaining({ decision_maker: null }), []));
  },
};

/** The owner is mandatory: clearing it disables Save. */
export const OwnerIsRequired: Story = {
  play: async () => {
    const body = within(document.body);
    await userEvent.type(body.getByLabelText("Decision title"), "Adopt PostgreSQL");
    await userEvent.type(body.getByLabelText("Decision statement"), "Use PostgreSQL as the backing store.");
    await expect(body.getByRole("button", { name: "Save" })).toBeEnabled();
    await userEvent.click(body.getByRole("button", { name: "Clear: Owner" }));
    await expect(body.getByRole("button", { name: "Save" })).toBeDisabled();
  },
};

export const EditExisting: Story = {
  args: {
    initial: {
      id: "decision-1", project_id: "project-1", unique_code: "DEC-001", title: "Adopt PostgreSQL",
      decision_statement: "Use PostgreSQL as the backing store.", decision_type_id: "dt-1", status: "draft",
      decision_date: null, decision_maker: null,
      owner: { type: "org_group", id: "group-1", label: "Platform Architecture", member_count: 2, exists: true },
      context: "Legacy MySQL is EOL.",
      options_considered: null, chosen_option: null, rationale: null, consequences: null, assumptions: null,
      constraints: null, creator_id: "user-1", is_archived: false, archived_at: null, archived_by: null,
      is_locked: false, created_at: "2026-01-10T09:00:00Z", updated_at: "2026-01-10T09:00:00Z",
    } satisfies Decision,
  },
  play: async () => {
    const body = within(document.body);
    await expect(body.getByRole("heading", { name: "Edit DEC-001" })).toBeInTheDocument();
    await expect(body.getByDisplayValue("Legacy MySQL is EOL.")).toBeInTheDocument();
    await expect(body.queryByLabelText("Start from a template (optional)")).not.toBeInTheDocument();
    // The existing group owner shows its name, kind and member count.
    await expect(body.getByText("Platform Architecture")).toBeInTheDocument();
    await expect(body.getByText("Org group · 2 members")).toBeInTheDocument();
  },
};

/** The page loads decision types in parallel, so the form can open before
 * they arrive; it must adopt the first type once they do, or Save stays
 * disabled for good (regression, 2026-10-04). */
export const TypesArriveAfterOpening: Story = {
  render: (args) => {
    function Harness() {
      const [types, setTypes] = useState<DecisionTypeDefinition[]>([]);
      useEffect(() => {
        const timer = setTimeout(() => setTypes(DECISION_TYPES), 50);
        return () => clearTimeout(timer);
      }, []);
      return <DecisionFormModal {...args} decisionTypes={types} />;
    }
    return <Harness />;
  },
  play: async ({ args }) => {
    const body = within(document.body);
    await userEvent.type(await body.findByLabelText("Decision title"), "Adopt PostgreSQL");
    await userEvent.type(body.getByLabelText("Decision statement"), "Use PostgreSQL.");
    const save = body.getByRole("button", { name: "Save" });
    await waitFor(() => expect(save).toBeEnabled());
    await userEvent.click(save);
    await expect(args.onSave).toHaveBeenCalledWith(expect.objectContaining({ decision_type_id: DECISION_TYPES[0].id }), []);
  },
};

/** Worst case: a long save error and a long unbroken title. The error is shown, and the dialog neither scrolls
 * sideways nor pushes Save out of reach. */
export const LongErrorAndLongTitleKeepTheActionsReachable: Story = {
  args: { error: "Could not save: " + "the server rejected this request for a reason that takes a while to explain. ".repeat(4) },
  play: async () => {
    const body = within(document.body);
    await userEvent.type(body.getByLabelText("Decision title"), "W".repeat(200));
    await expect(body.getByText(/Could not save:/)).toBeVisible();
    await expect(body.getByRole("button", { name: "Save" })).toBeVisible();
    const dialog = body.getByRole("dialog");
    await expect(dialog.scrollWidth).toBeLessThanOrEqual(dialog.clientWidth + 1);
  },
};

export const LightTheme: Story = { ...CreateNew };
export const DarkTheme: Story = { ...CreateNew, globals: { theme: "dark" } };
