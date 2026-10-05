import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import type { OrgUser } from "../../api/types";
import { buildProject, buildUser, withAuth, withRouter, withToast } from "../../testing/storybook-helpers";
import { buildNeed, buildPersona, buildStakeholder } from "./fixtures";
import { NeedDetailPage } from "./NeedDetailPage";
import type { Need, NeedHolder, NeedRequirement } from "./types";

const PROJECT_ID = "project-1";
const NEED_ID = "need-1";
const BASE = `/api/v1/projects/${PROJECT_ID}/modules/stakeholders`;

const ORG_USERS: OrgUser[] = [
  {
    user_id: "user-2", email: "jamie.lee@example.com", display_name: "Jamie Lee", is_active: true, is_archived: false,
    roles: ["member"], display_name_locked: false, last_login_at: null, is_2fa_enabled: false, module_roles: [], custom_roles: [],
  },
];

const HOLDERS: NeedHolder[] = [
  { link_id: "h1", kind: "stakeholder", id: "stakeholder-1", name: "Pat Regulator", scope: "project" },
  { link_id: "h2", kind: "persona", id: "persona-1", name: "Field Technician", scope: "project" },
];
const REQUIREMENTS: NeedRequirement[] = [{ link_id: "r1", id: "req-1", unique_code: "SW-PERF-001", title: "Remote diagnostics in 30 seconds" }];

interface Mocks {
  versions?: unknown[];
  holders?: NeedHolder[];
  requirements?: NeedRequirement[];
}

function mockDetailApis(current: Need, { versions = [], holders = HOLDERS, requirements = REQUIREMENTS }: Mocks = {}) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === `/api/v1/projects/${PROJECT_ID}`) return buildProject({ id: PROJECT_ID, organization_id: "org-1" });
    if (path === "/api/v1/orgs/org-1/users") return ORG_USERS;
    if (path.startsWith("/api/v1/orgs/org-1/users/search")) return { members: ORG_USERS, external: null };
    if (path === `${BASE}/stakeholders`) return [buildStakeholder()];
    if (path === `${BASE}/personas`) return [buildPersona()];
    if (path === `/api/v1/projects/${PROJECT_ID}/requirements`) {
      return [{ id: "req-1", unique_code: "SW-PERF-001", name: "Remote diagnostics in 30 seconds" }, { id: "req-2", unique_code: "SW-PERF-002", name: "Offline mode" }];
    }
    if (path === `${BASE}/needs/${NEED_ID}/holders`) return holders;
    if (path === `${BASE}/needs/${NEED_ID}/requirements`) return requirements;
    if (path === `${BASE}/needs/${NEED_ID}`) return current;
    if (path.endsWith("/versions")) return versions;
    if (path.endsWith("/comments")) return [];
    if (path.endsWith("/files")) return [];
    throw new Error(`Unmocked GET: ${path}`);
  });
}

const meta: Meta<typeof NeedDetailPage> = {
  title: "Modules/Stakeholders/NeedDetailPage",
  component: NeedDetailPage,
  decorators: [
    withAuth(buildUser({ id: "user-1", display_name: "Alex Morgan" })),
    withRouter(`/projects/${PROJECT_ID}/modules/stakeholders/needs/${NEED_ID}`, "/projects/:projectId/modules/stakeholders/needs/:needId"),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof NeedDetailPage>;

export const ActiveShowsFieldsAndLinks: Story = {
  beforeEach: () => mockDetailApis(buildNeed()),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Diagnose faults quickly" })).toBeInTheDocument());
    await expect(canvas.getByText("Active", { exact: true })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Retire" })).toBeInTheDocument();
    await expect(canvas.queryByText("active")).not.toBeInTheDocument();
    await expect(canvas.getByText("Observed on site visits; each delay costs an hour.")).toBeInTheDocument();
    await waitFor(() => expect(canvas.getByRole("link", { name: "Pat Regulator" })).toBeInTheDocument());
    await expect(canvas.getByRole("link", { name: "Pat Regulator" })).toHaveAttribute("href", `/projects/${PROJECT_ID}/modules/stakeholders/stakeholders/stakeholder-1`);
    await expect(canvas.getByRole("link", { name: "Field Technician" })).toHaveAttribute("href", `/projects/${PROJECT_ID}/modules/stakeholders/personas/persona-1`);
    await expect(canvas.getByRole("link", { name: "SW-PERF-001 Remote diagnostics in 30 seconds" })).toHaveAttribute("href", `/projects/${PROJECT_ID}/requirements/req-1`);
  },
};

export const DraftOffersActivateAndRetire: Story = {
  beforeEach: () => mockDetailApis(buildNeed({ status: "draft" })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Activate" })).toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "Retire" })).toBeInTheDocument();
  },
};

export const RetireAsksForConfirmation: Story = {
  beforeEach: () => {
    mockDetailApis(buildNeed());
    spyOn(api, "post").mockResolvedValue(buildNeed({ status: "retired" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Retire" }));
    await userEvent.click(canvas.getByRole("button", { name: "Retire" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "Retire this Stakeholder Need?" }));
    await userEvent.type(dialog.getByLabelText("Transition comment"), "Superseded");
    await userEvent.click(dialog.getByRole("button", { name: "Retire" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`${BASE}/needs/${NEED_ID}/retire`, { comment: "Superseded" }));
    await waitFor(() => expect(canvas.getByText("Retired", { exact: true })).toBeInTheDocument());
  },
};

export const ArchiveAsksForConfirmation: Story = {
  beforeEach: () => {
    mockDetailApis(buildNeed());
    spyOn(api, "post").mockResolvedValue(buildNeed({ is_archived: true }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Archive" }));
    await userEvent.click(canvas.getByRole("button", { name: "Archive" }));
    await userEvent.click(within(within(document.body).getByRole("dialog", { name: "Archive this Stakeholder Need?" })).getByRole("button", { name: "Archive" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`${BASE}/needs/${NEED_ID}/archive`));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Unarchive" })).toBeInTheDocument());
  },
};

export const AddsAHolderFromTheUnlinkedCandidates: Story = {
  beforeEach: () => {
    mockDetailApis(buildNeed(), { holders: [HOLDERS[1]] });
    spyOn(api, "post").mockResolvedValue(HOLDERS[0]);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("combobox", { name: "Stakeholder with this need" }));
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Stakeholder with this need" }), "stakeholder-1");
    await userEvent.click(canvas.getAllByRole("button", { name: "Add" })[0]);
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`${BASE}/needs/${NEED_ID}/holders`, { kind: "stakeholder", id: "stakeholder-1" }),
    );
  },
};

export const RemovesAHolderBehindAConfirm: Story = {
  beforeEach: () => {
    mockDetailApis(buildNeed());
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Remove Pat Regulator" }));
    await userEvent.click(canvas.getByRole("button", { name: "Remove Pat Regulator" }));
    await userEvent.click(within(within(document.body).getByRole("dialog", { name: "Remove Pat Regulator?" })).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`${BASE}/needs/${NEED_ID}/holders/stakeholder/stakeholder-1`));
  },
};

export const LinksARequirement: Story = {
  beforeEach: () => {
    mockDetailApis(buildNeed());
    spyOn(api, "post").mockResolvedValue({ link_id: "r2", id: "req-2", unique_code: "SW-PERF-002", title: "Offline mode" });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("combobox", { name: "Requirement it gave rise to" }));
    // The already-linked requirement is not offered again.
    await expect(canvas.queryByRole("option", { name: "SW-PERF-001 Remote diagnostics in 30 seconds" })).not.toBeInTheDocument();
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Requirement it gave rise to" }), "req-2");
    await userEvent.click(canvas.getAllByRole("button", { name: "Add" })[2]);
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`${BASE}/needs/${NEED_ID}/requirements`, { requirement_id: "req-2" }));
  },
};

export const OwnerCanBeAssigned: Story = {
  beforeEach: () => {
    mockDetailApis(buildNeed());
    spyOn(api, "put").mockResolvedValue(buildNeed({ owner_id: "user-2" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByLabelText("Need owner"));
    await userEvent.type(canvas.getByLabelText("Need owner"), "Jamie");
    await waitFor(() => canvas.getByText(/Jamie Lee/));
    await userEvent.click(canvas.getByText(/Jamie Lee/));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(`${BASE}/needs/${NEED_ID}`, { owner_id: "user-2" }));
  },
};

export const VersionHistoryUsesLabels: Story = {
  beforeEach: () =>
    mockDetailApis(buildNeed({ version_number: 2 }), {
      versions: [
        { id: "v1", need_id: NEED_ID, version_number: 1, valid_from: "2026-01-10T09:00:00Z", valid_to: "2026-01-11T09:00:00Z", name: "Diagnose faults quickly", status: "draft", change_note: "Initial creation.", created_at: "2026-01-10T09:00:00Z" },
        { id: "v2", need_id: NEED_ID, version_number: 2, valid_from: "2026-01-11T09:00:00Z", valid_to: null, name: "Diagnose faults quickly", status: "active", change_note: "Activated", created_at: "2026-01-11T09:00:00Z" },
      ],
    }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Version history" })).toBeInTheDocument());
    await expect(canvas.getByText("Initial creation.")).toBeInTheDocument();
    await expect(canvas.queryByText("draft")).not.toBeInTheDocument();
  },
};

export const EditOpensThePrefilledForm: Story = {
  beforeEach: () => mockDetailApis(buildNeed()),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Edit" }));
    await userEvent.click(canvas.getByRole("button", { name: "Edit" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "Edit Diagnose faults quickly" }));
    await expect(dialog.getByLabelText("Need name")).toHaveValue("Diagnose faults quickly");
    await expect(dialog.getByLabelText("Rationale")).toHaveValue("Observed on site visits; each delay costs an hour.");
  },
};

export const LightTheme: Story = { ...ActiveShowsFieldsAndLinks };
export const DarkTheme: Story = { ...ActiveShowsFieldsAndLinks, globals: { theme: "dark" } };
