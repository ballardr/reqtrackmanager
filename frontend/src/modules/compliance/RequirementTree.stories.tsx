import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { RequirementTree } from "./RequirementTree";
import type { ComplianceActionType, ComplianceRequiredAction, ComplianceRequirement } from "./types";

const ORG_ID = "org-1";
const STANDARD_ID = "std-1";
const VERSION_ID = "ver-1";
const BASE = `/api/v1/orgs/${ORG_ID}/modules/compliance`;
const REQUIREMENTS_BASE = `${BASE}/standards/${STANDARD_ID}/versions/${VERSION_ID}/requirements`;

const ACTION_TYPES: ComplianceActionType[] = [
  { id: "at-1", organization_id: ORG_ID, name: "Review", sort_order: 0 },
  { id: "at-2", organization_id: ORG_ID, name: "Sign-off", sort_order: 1 },
];

function req(overrides: Partial<ComplianceRequirement> & { id: string; name: string }): ComplianceRequirement {
  return {
    standard_version_id: VERSION_ID, parent_requirement_id: null, reference: null, description: "",
    reasoning: "", sort_order: 0, created_by: "user-1", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function action(overrides: Partial<ComplianceRequiredAction> & { id: string; requirement_id: string; name: string; action_type_id: string }): ComplianceRequiredAction {
  return {
    description: "", is_mandatory: true, sort_order: 0, created_by: "user-1",
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", ...overrides,
  };
}

/**
 * `RequirementTree` is fully self-contained — it fetches its own
 * requirements/required-actions and owns every mutation directly against
 * `complianceApi` (unlike `ProjectTree`, whose `nodes` shape this component
 * otherwise follows, see its own docstring). This stateful mock reproduces
 * the backend's flat, DFS-ordered `GET .../requirements` list plus its
 * `required-actions` sub-resource, so a story's `play` function can assert
 * a real create/reorder/delete -> reload -> re-render round trip, matching
 * `ComplianceAdminPanel.stories.tsx`'s own standard.
 *
 * Opening "View mappings" mounts `RequirementMappingsModal` as a child —
 * its endpoints are mocked here just enough to resolve emptily so that
 * transition settles cleanly; that modal's own CRUD/cascading-picker
 * behaviour is `RequirementMappingsModal.stories.tsx`'s job, not
 * duplicated here.
 */
function mockRequirementTreeApis(initialRequirements: ComplianceRequirement[], initialActions: Record<string, ComplianceRequiredAction[]> = {}) {
  let requirements = initialRequirements;
  const actionsByReq: Record<string, ComplianceRequiredAction[]> = { ...initialActions };

  function siblingsOf(parentId: string | null): ComplianceRequirement[] {
    return requirements.filter((r) => r.parent_requirement_id === parentId).sort((a, b) => a.sort_order - b.sort_order);
  }

  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.includes("/mappings")) return [];
    if (path.includes("/mapping-relationship-types")) return [];
    if (path.includes("/standards?")) return [];
    if (path.includes("/required-actions")) {
      const reqId = path.split(`${REQUIREMENTS_BASE}/`)[1].split("/required-actions")[0];
      return actionsByReq[reqId] ?? [];
    }
    if (path === REQUIREMENTS_BASE) {
      return [...requirements].sort((a, b) => a.sort_order - b.sort_order);
    }
    throw new Error(`unmocked GET: ${path}`);
  });

  spyOn(api, "post").mockImplementation(async (path: string, body?: unknown) => {
    if (path.includes("/required-actions/") && path.endsWith("/move")) {
      const [reqId, actionId] = path.split(`${REQUIREMENTS_BASE}/`)[1].split("/required-actions/");
      const id = actionId.replace("/move", "");
      const direction = (body as { direction: "up" | "down" }).direction;
      const list = (actionsByReq[reqId] ?? []).sort((a, b) => a.sort_order - b.sort_order);
      const idx = list.findIndex((a) => a.id === id);
      const swapWith = direction === "up" ? idx - 1 : idx + 1;
      if (swapWith >= 0 && swapWith < list.length) {
        const tmp = list[idx].sort_order;
        list[idx].sort_order = list[swapWith].sort_order;
        list[swapWith].sort_order = tmp;
      }
      actionsByReq[reqId] = list;
      return list.find((a) => a.id === id);
    }
    if (path.endsWith("/move")) {
      const reqId = path.split(`${REQUIREMENTS_BASE}/`)[1].replace("/move", "");
      const direction = (body as { direction: "up" | "down" }).direction;
      const item = requirements.find((r) => r.id === reqId)!;
      const siblings = siblingsOf(item.parent_requirement_id);
      const idx = siblings.findIndex((r) => r.id === reqId);
      const swapWith = direction === "up" ? idx - 1 : idx + 1;
      if (swapWith >= 0 && swapWith < siblings.length) {
        const tmp = siblings[idx].sort_order;
        siblings[idx].sort_order = siblings[swapWith].sort_order;
        siblings[swapWith].sort_order = tmp;
      }
      return item;
    }
    if (path.includes("/required-actions")) {
      const reqId = path.split(`${REQUIREMENTS_BASE}/`)[1].split("/required-actions")[0];
      const payload = body as { action_type_id: string; name: string; description?: string; is_mandatory?: boolean };
      const list = actionsByReq[reqId] ?? [];
      const created = action({
        id: `act-${Object.values(actionsByReq).flat().length + 1}`, requirement_id: reqId,
        action_type_id: payload.action_type_id, name: payload.name, description: payload.description ?? "",
        is_mandatory: payload.is_mandatory ?? true, sort_order: list.length,
      });
      actionsByReq[reqId] = [...list, created];
      return created;
    }
    if (path === REQUIREMENTS_BASE) {
      const payload = body as { parent_requirement_id: string | null; reference: string | null; name: string; description?: string; reasoning?: string };
      const created = req({
        id: `req-${requirements.length + 1}`, parent_requirement_id: payload.parent_requirement_id,
        reference: payload.reference, name: payload.name, description: payload.description ?? "",
        reasoning: payload.reasoning ?? "", sort_order: siblingsOf(payload.parent_requirement_id).length,
      });
      requirements = [...requirements, created];
      return created;
    }
    throw new Error(`unmocked POST: ${path}`);
  });

  spyOn(api, "patch").mockImplementation(async (path: string, body?: unknown) => {
    if (path.includes("/required-actions/")) {
      const [reqId, actionId] = path.split(`${REQUIREMENTS_BASE}/`)[1].split("/required-actions/");
      const payload = body as { action_type_id: string; name: string; description?: string; is_mandatory?: boolean };
      actionsByReq[reqId] = (actionsByReq[reqId] ?? []).map((a) => (a.id === actionId ? { ...a, ...payload } : a));
      return actionsByReq[reqId].find((a) => a.id === actionId);
    }
    const reqId = path.split(`${REQUIREMENTS_BASE}/`)[1];
    const payload = body as { reference?: string | null; name: string; description?: string; reasoning?: string };
    requirements = requirements.map((r) => (r.id === reqId ? { ...r, ...payload } : r));
    return requirements.find((r) => r.id === reqId);
  });

  spyOn(api, "delete").mockImplementation(async (path: string) => {
    if (path.includes("/required-actions/")) {
      const [reqId, actionId] = path.split(`${REQUIREMENTS_BASE}/`)[1].split("/required-actions/");
      actionsByReq[reqId] = (actionsByReq[reqId] ?? []).filter((a) => a.id !== actionId);
      return;
    }
    const reqId = path.split(`${REQUIREMENTS_BASE}/`)[1];
    requirements = requirements.filter((r) => r.id !== reqId && r.parent_requirement_id !== reqId);
  });
}

const meta: Meta<typeof RequirementTree> = {
  title: "Modules/Compliance/RequirementTree",
  component: RequirementTree,
  args: { orgId: ORG_ID, standardId: STANDARD_ID, versionId: VERSION_ID, isDraft: true, actionTypes: ACTION_TYPES },
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof RequirementTree>;

export const AddRootRequirementToEmptyTree: Story = {
  beforeEach: () => mockRequirementTreeApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No requirements defined for this version yet.")).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: "Add requirement" }));
    const body = within(document.body);
    await userEvent.type(body.getByLabelText("Requirement name"), "Access control policy");
    await userEvent.click(body.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      REQUIREMENTS_BASE,
      { parent_requirement_id: null, reference: null, name: "Access control policy", description: "", reasoning: "" }
    ));
    await waitFor(() => expect(canvas.getByText("Access control policy")).toBeInTheDocument());
  },
};

export const ExpandLoadsRequiredActionsLazily: Story = {
  beforeEach: () => mockRequirementTreeApis(
    [req({ id: "req-1", reference: "A.5.1", name: "Information security policy" })],
    { "req-1": [action({ id: "act-1", requirement_id: "req-1", action_type_id: "at-1", name: "Annual review", sort_order: 0 })] }
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Information security policy")).toBeInTheDocument());
    await expect(canvas.queryByText("Annual review")).not.toBeInTheDocument();

    await userEvent.click(canvas.getByRole("button", { name: "Expand Information security policy" }));
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(`${REQUIREMENTS_BASE}/req-1/required-actions`));
    await expect(await canvas.findByText("Annual review")).toBeInTheDocument();
    await expect(canvas.getByText("(mandatory)")).toBeInTheDocument();
    // Requirements list (mount) + one required-actions fetch (this expand).
    await expect(api.get).toHaveBeenCalledTimes(2);

    await userEvent.click(canvas.getByRole("button", { name: "Collapse Information security policy" }));
    await userEvent.click(canvas.getByRole("button", { name: "Expand Information security policy" }));
    // Re-expanding a requirement whose actions are already cached doesn't
    // re-fetch them (`toggleExpand`'s `if (!actionsByRequirement[id])` guard)
    // — the call count stays at 2, not 3.
    await expect(api.get).toHaveBeenCalledTimes(2);
  },
};

export const AddChildRequirementNestsUnderParent: Story = {
  beforeEach: () => mockRequirementTreeApis([req({ id: "req-1", name: "Access control" })]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Access control")).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: "Add child requirement under Access control" }));
    const body = within(document.body);
    await userEvent.type(body.getByLabelText("Requirement name"), "User access provisioning");
    await userEvent.click(body.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      REQUIREMENTS_BASE,
      { parent_requirement_id: "req-1", reference: null, name: "User access provisioning", description: "", reasoning: "" }
    ));
    await waitFor(() => expect(canvas.getByText("User access provisioning")).toBeInTheDocument());
    // Nested under its parent — indented via `depth`, and only reachable
    // (still exists) once the parent's own list item contains it.
    const parentItem = canvas.getByText("Access control").closest("li")!;
    await expect(within(parentItem).getByText("User access provisioning")).toBeInTheDocument();
  },
};

export const ReorderMovesRequirementDown: Story = {
  beforeEach: () => mockRequirementTreeApis([
    req({ id: "req-1", name: "Access control", sort_order: 0 }),
    req({ id: "req-2", name: "Asset management", sort_order: 1 }),
  ]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Access control")).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: "Move Access control down" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`${REQUIREMENTS_BASE}/req-1/move`, { direction: "down" }));

    // Top-level requirements render as `<li>` siblings of one `<ul>` — check
    // DOM order directly rather than relying on an ARIA list role, which
    // `list-style: none` (used here) suppresses in some environments.
    await waitFor(() => {
      const list = canvasElement.querySelector("ul");
      expect(list?.children[0]?.textContent).toContain("Asset management");
    });
  },
};

export const EditRequirement: Story = {
  beforeEach: () => mockRequirementTreeApis([req({ id: "req-1", reference: "A.5.1", name: "Access control" })]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Access control")).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: "Edit Access control" }));
    const body = within(document.body);
    const nameInput = body.getByLabelText("Requirement name");
    await userEvent.clear(nameInput);
    await userEvent.type(nameInput, "Access control policy");
    await userEvent.click(body.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(api.patch).toHaveBeenCalledWith(
      `${REQUIREMENTS_BASE}/req-1`,
      { reference: "A.5.1", name: "Access control policy", description: "", reasoning: "" }
    ));
    await waitFor(() => expect(canvas.getByText("Access control policy")).toBeInTheDocument());
  },
};

export const DeleteRequirementWithConfirm: Story = {
  beforeEach: () => mockRequirementTreeApis([req({ id: "req-1", name: "Access control" })]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Access control")).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: "Delete Access control" }));
    const body = within(document.body);
    await expect(body.getByText(/This also deletes every child requirement/)).toBeInTheDocument();
    await userEvent.click(body.getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`${REQUIREMENTS_BASE}/req-1`));
    await waitFor(() => expect(canvas.getByText("No requirements defined for this version yet.")).toBeInTheDocument());
  },
};

export const RequiredActionAddEditMoveAndDelete: Story = {
  beforeEach: () => mockRequirementTreeApis(
    [req({ id: "req-1", name: "Access control" })],
    { "req-1": [action({ id: "act-1", requirement_id: "req-1", action_type_id: "at-1", name: "Annual review", sort_order: 0 })] }
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Access control")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Expand Access control" }));
    await expect(await canvas.findByText("Annual review")).toBeInTheDocument();

    // Add a second required action.
    await userEvent.click(canvas.getByRole("button", { name: "Add required action" }));
    const body = within(document.body);
    await userEvent.type(body.getByLabelText("Required action name"), "Sign-off by CISO");
    await userEvent.selectOptions(body.getByLabelText("Action type"), "at-2");
    await userEvent.click(body.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `${REQUIREMENTS_BASE}/req-1/required-actions`,
      { action_type_id: "at-2", name: "Sign-off by CISO", description: "", is_mandatory: true }
    ));
    await expect(await canvas.findByText("Sign-off by CISO")).toBeInTheDocument();

    // Move it up ahead of "Annual review".
    await userEvent.click(canvas.getByRole("button", { name: "Move required action Sign-off by CISO up" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `${REQUIREMENTS_BASE}/req-1/required-actions/act-2/move`,
      { direction: "up" }
    ));

    // Edit "Annual review".
    await userEvent.click(canvas.getByRole("button", { name: "Edit required action Annual review" }));
    const editNameInput = within(document.body).getByLabelText("Required action name");
    await userEvent.clear(editNameInput);
    await userEvent.type(editNameInput, "Biennial review");
    await userEvent.click(within(document.body).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith(
      `${REQUIREMENTS_BASE}/req-1/required-actions/act-1`,
      { action_type_id: "at-1", name: "Biennial review", description: "", is_mandatory: true }
    ));

    // Delete "Sign-off by CISO".
    await userEvent.click(canvas.getByRole("button", { name: "Delete required action Sign-off by CISO" }));
    await userEvent.click(within(document.body).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`${REQUIREMENTS_BASE}/req-1/required-actions/act-2`));
    await waitFor(() => expect(canvas.queryByText("Sign-off by CISO")).not.toBeInTheDocument());
  },
};

export const ViewMappingsOpensMappingsModal: Story = {
  beforeEach: () => mockRequirementTreeApis([req({ id: "req-1", name: "Access control" })]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Access control")).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: "View mappings for Access control" }));

    // Proves the transition only — `RequirementMappingsModal`'s own
    // mapping-CRUD/cascading-picker behaviour is
    // `RequirementMappingsModal.stories.tsx`'s job.
    await expect(within(document.body).getByRole("dialog", { name: 'Mappings for "Access control"' })).toBeInTheDocument();
  },
};

export const ReadOnlyWhenVersionNotDraft: Story = {
  args: { isDraft: false },
  beforeEach: () => mockRequirementTreeApis(
    [req({ id: "req-1", name: "Access control" })],
    { "req-1": [action({ id: "act-1", requirement_id: "req-1", action_type_id: "at-1", name: "Annual review", sort_order: 0 })] }
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Access control")).toBeInTheDocument());
    await expect(canvas.queryByRole("button", { name: "Add requirement" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Edit Access control" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Delete Access control" })).not.toBeInTheDocument();
    // "View mappings" stays available — mappings aren't a mutation of this
    // version's own (immutable) requirement content.
    await expect(canvas.getByRole("button", { name: "View mappings for Access control" })).toBeInTheDocument();

    await userEvent.click(canvas.getByRole("button", { name: "Expand Access control" }));
    await expect(await canvas.findByText("Annual review")).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Add required action" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Edit required action Annual review" })).not.toBeInTheDocument();
  },
};

export const LoadErrorShowsInlineMessage: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockRejectedValue(new Error("Could not load requirements."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Could not load requirements.")).toBeInTheDocument());
  },
};

export const LightTheme: Story = { ...ExpandLoadsRequiredActionsLazily };
export const DarkTheme: Story = { ...ExpandLoadsRequiredActionsLazily, globals: { theme: "dark" } };
