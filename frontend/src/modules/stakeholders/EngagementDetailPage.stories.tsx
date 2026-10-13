import type { Meta, StoryObj } from "@storybook/react-vite";
import { Route, Routes, MemoryRouter, useLocation } from "react-router-dom";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../../api/client";
import type { OrgGroup, OrgUser, Principal, ProjectGroup } from "../../api/types";
import { buildGraph, buildGraphNode } from "../../testing/artefactLinksFixtures";
import { buildProject, buildUser, withAuth, withToast } from "../../testing/storybook-helpers";
import { EngagementDetailPage } from "./EngagementDetailPage";
import { buildEngagement, buildFinding, buildPersona, buildStakeholder, buildStakeholderGroup } from "./fixtures";
import type {
  AnonymousParticipant, Engagement, EngagementAudience, EngagementOutcome, EngagementParticipant, EngagementPersona,
  EngagementPrompt,
} from "./types";

const PROJECT_ID = "project-1";
const ENGAGEMENT_ID = "engagement-1";
const BASE = `/api/v1/projects/${PROJECT_ID}/modules/stakeholders`;
const EBASE = `${BASE}/engagements/${ENGAGEMENT_ID}`;
const DETAIL_PATH = `/projects/${PROJECT_ID}/modules/stakeholders/engagements/${ENGAGEMENT_ID}`;

const ORG_USERS: OrgUser[] = [
  {
    user_id: "user-2", email: "jamie.lee@example.com", display_name: "Jamie Lee", is_active: true, is_archived: false,
    roles: ["member"], display_name_locked: false, last_login_at: null, is_2fa_enabled: false, module_roles: [], custom_roles: [],
  },
];
const ORG_GROUPS: OrgGroup[] = [
  { id: "group-1", name: "Platform Architecture", member_user_ids: ["user-2"], member_org_group_ids: [], idp_synced_group_name: null, granted_org_role: null },
];
const PROJECT_GROUPS: ProjectGroup[] = [];
const TEAM: Principal = { type: "org_group", id: "group-1", label: "Platform Architecture", member_count: 3, exists: true };

const PARTICIPANTS: EngagementParticipant[] = [{ link_id: "pa1", stakeholder_id: "stakeholder-1", name: "Pat Regulator", scope: "project" }];
const PERSONAS: EngagementPersona[] = [{ link_id: "pe1", persona_id: "persona-1", name: "Field Technician", scope: "project" }];
const AUDIENCES: EngagementAudience[] = [{ link_id: "au1", group_id: "g-client", name: "Client", scope: "organization" }];
const OUTCOMES: EngagementOutcome[] = [{ link_id: "o1", kind: "raised", target_type: "pain_point", target_id: "pp-1", label: "Reports arrive late" }];
const PROMPTS: EngagementPrompt[] = [
  { id: "pr1", engagement_id: ENGAGEMENT_ID, sort_order: 0, prompt: "Walk me through an inspection", response_notes: "Starts with the checklist." },
];
const ANONYMOUS: AnonymousParticipant[] = [
  { id: "ap1", engagement_id: ENGAGEMENT_ID, label: "Participant 1", persona_id: "persona-1", persona_name: "Field Technician" },
];

interface Mocks {
  researchExtras?: boolean;
}

function mockDetailApis(current: Engagement, { researchExtras = false }: Mocks = {}) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === `/api/v1/projects/${PROJECT_ID}`) return buildProject({ id: PROJECT_ID, organization_id: "org-1" });
    if (path === "/api/v1/orgs/org-1/groups") return ORG_GROUPS;
    if (path === `/api/v1/projects/${PROJECT_ID}/groups`) return PROJECT_GROUPS;
    if (path === "/api/v1/orgs/org-1/users") return ORG_USERS;
    if (path.startsWith("/api/v1/orgs/org-1/users/search")) return { members: ORG_USERS, external: null };
    if (path === `${BASE}/subcomponents`) {
      return [{ module_key: "stakeholders", subcomponent_key: "research_extras", name: "Research extras", effective_enabled: researchExtras }];
    }
    if (path === `${BASE}/stakeholders`) return [buildStakeholder(), buildStakeholder({ id: "stakeholder-2", name: "Sam Client" })];
    if (path === `${BASE}/personas`) return [buildPersona()];
    if (path === `${BASE}/stakeholder-groups`) return [buildStakeholderGroup({ id: "g-client", name: "Client" }), buildStakeholderGroup({ id: "g-ops", name: "Operations" })];
    if (path.includes(`/artefacts/engagement/${ENGAGEMENT_ID}/link-graph`)) {
      return buildGraph([[buildGraphNode({ type: "pain_point", id: "pp-1", type_label: "Pain Point", label: "Reports arrive late", status: null })]]);
    }
    if (path === EBASE) return current;
    if (path === `${EBASE}/participants`) return PARTICIPANTS;
    if (path === `${EBASE}/personas`) return PERSONAS;
    if (path === `${EBASE}/audiences`) return AUDIENCES;
    if (path === `${EBASE}/outcomes`) return OUTCOMES;
    if (path.startsWith(`${BASE}/engagement-outcome-targets`)) return [];
    if (path === `${EBASE}/prompts`) return PROMPTS;
    if (path === `${EBASE}/anonymous-participants`) return ANONYMOUS;
    if (path === `${EBASE}/findings`) return [buildFinding()];
    if (path === `${BASE}/findings/finding-1/outcomes`) return [];
    if (path.endsWith("/comments")) return [];
    if (path.endsWith("/files")) return [];
    throw new Error(`Unmocked GET: ${path}`);
  });
}

/** Shows the current location, rendered by the catch-all route so navigation away from the page can be asserted. */
function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

const meta: Meta<typeof EngagementDetailPage> = {
  title: "Modules/Stakeholders/EngagementDetailPage",
  component: EngagementDetailPage,
  decorators: [
    withAuth(buildUser({ id: "user-1", display_name: "Alex Morgan" })),
    (Story) => (
      <MemoryRouter initialEntries={[DETAIL_PATH]}>
        <Routes>
          <Route path="/projects/:projectId/modules/stakeholders/engagements/:engagementId" element={<Story />} />
          <Route path="*" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>
    ),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof EngagementDetailPage>;

export const ShowsFieldsPeopleAndOutcomes: Story = {
  beforeEach: () => mockDetailApis(buildEngagement({ retain_until: "2027-03-12" })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Quarterly review with the regulator" })).toBeInTheDocument());
    // Channel renders through its label map.
    await expect(canvas.getByText("Meeting", { exact: true })).toBeInTheDocument();
    await expect(canvas.queryByText("meeting")).not.toBeInTheDocument();
    await expect(canvas.getByText("Walk through the audit findings.")).toBeInTheDocument();
    await expect(canvas.getByText("Agreed to share evidence by the end of April.")).toBeInTheDocument();
    await expect(canvas.getByTestId("consent")).toHaveTextContent("Consent recorded: Yes");
    await expect(canvas.getByTestId("retention")).toHaveTextContent("Retain until 2027-03-12");
    await waitFor(() => expect(canvas.getByRole("link", { name: "Pat Regulator" })).toHaveAttribute("href", `/projects/${PROJECT_ID}/modules/stakeholders/stakeholders/stakeholder-1`));
    await expect(canvas.getByRole("link", { name: "Field Technician" })).toHaveAttribute("href", `/projects/${PROJECT_ID}/modules/stakeholders/personas/persona-1`);
    await waitFor(() => expect(canvas.getByText(/Raised · Pain Point:/)).toBeInTheDocument());
    await expect(canvas.getByText("Client")).toBeInTheDocument();
  },
};

/** Past the retain-until date the engagement is flagged for review; nothing is deleted. */
export const RetentionDueIsFlagged: Story = {
  beforeEach: () => mockDetailApis(buildEngagement({ retain_until: "2026-04-01", retention_due: true })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Retention review due")).toBeInTheDocument());
    await expect(canvas.getByTestId("retention")).toHaveTextContent("the date has been reached");
  },
};

/** With the research extras off the core log still works and the extras blocks are not rendered. */
export const ResearchExtrasHiddenWhenOff: Story = {
  beforeEach: () => mockDetailApis(buildEngagement(), { researchExtras: false }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("link", { name: "Pat Regulator" }));
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(`${BASE}/subcomponents`));
    await expect(canvas.queryByText("Session prompts")).not.toBeInTheDocument();
    await expect(canvas.queryByText("Anonymous participants")).not.toBeInTheDocument();
    await expect(canvas.queryByText("Findings")).not.toBeInTheDocument();
  },
};

export const ResearchExtrasShownWhenOn: Story = {
  beforeEach: () => mockDetailApis(buildEngagement({ anonymous_participant_count: 1 }), { researchExtras: true }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Session prompts")).toBeInTheDocument());
    await expect(canvas.getByText("Walk me through an inspection")).toBeInTheDocument();
    await expect(canvas.getByText("Participant 1 · Field Technician")).toBeInTheDocument();
    await expect(canvas.getByText("Technicians skip the checklist when offline")).toBeInTheDocument();
  },
};

export const AddsAParticipantFromTheUnlinkedCandidates: Story = {
  beforeEach: () => {
    mockDetailApis(buildEngagement());
    spyOn(api, "post").mockResolvedValue({ link_id: "pa2", stakeholder_id: "stakeholder-2", name: "Sam Client", scope: "project" });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Add to Participants" }));
    await userEvent.click(canvas.getByRole("button", { name: "Add to Participants" }));
    const popover = within(within(document.body).getByRole("dialog", { name: "Add to Participants" }));
    // Pat already takes part, so is not offered again.
    await expect(popover.queryByRole("option", { name: "Pat Regulator" })).not.toBeInTheDocument();
    await userEvent.selectOptions(popover.getByRole("combobox", { name: "Stakeholder to add" }), "stakeholder-2");
    await userEvent.click(popover.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`${EBASE}/participants`, { stakeholder_id: "stakeholder-2" }));
  },
};

const PERSON: Principal = { type: "user", id: "user-2", label: "Jamie Lee (jamie@example.com)", member_count: null, exists: true };

/** An engagement can have several facilitators: adding one sends the whole new list, group or user alike. */
export const FacilitatorsCanBeAddedAsUsersOrGroups: Story = {
  beforeEach: () => {
    mockDetailApis(buildEngagement({ facilitators: [PERSON] }));
    spyOn(api, "put").mockResolvedValue(buildEngagement({ facilitators: [PERSON, TEAM] }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Add to Facilitators" }));
    await expect(canvas.getByText("Jamie Lee (jamie@example.com)")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Add to Facilitators" }));
    const popover = within(within(document.body).getByRole("dialog", { name: "Add to Facilitators" }));
    await userEvent.type(popover.getByLabelText("Engagement facilitator"), "platform");
    await userEvent.click(await popover.findByText("Platform Architecture"));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith(EBASE, {
        facilitators: [{ type: "user", id: "user-2" }, { type: "org_group", id: "group-1" }],
      }),
    );
    await waitFor(() => expect(canvas.getByText("Org group · 3 members")).toBeInTheDocument());
  },
};

/** Removing a facilitator sends the list without them; removing the last sends an empty list. */
export const FacilitatorCanBeRemoved: Story = {
  beforeEach: () => {
    mockDetailApis(buildEngagement({ facilitators: [PERSON] }));
    spyOn(api, "put").mockResolvedValue(buildEngagement({ facilitators: [] }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Remove Jamie Lee (jamie@example.com)" }));
    await userEvent.click(canvas.getByRole("button", { name: "Remove Jamie Lee (jamie@example.com)" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(EBASE, { facilitators: [] }));
    await waitFor(() => expect(canvas.getByText("Nobody is recorded as running it.")).toBeInTheDocument());
  },
};

export const EditOpensThePrefilledForm: Story = {
  beforeEach: () => {
    mockDetailApis(buildEngagement());
    spyOn(api, "put").mockResolvedValue(buildEngagement({ title: "Renamed review" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Edit" }));
    await userEvent.click(canvas.getByRole("button", { name: "Edit" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "Edit Quarterly review with the regulator" }));
    await expect(dialog.getByLabelText("Engagement title")).toHaveValue("Quarterly review with the regulator");
    await userEvent.clear(dialog.getByLabelText("Engagement title"));
    await userEvent.type(dialog.getByLabelText("Engagement title"), "Renamed review");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(EBASE, expect.objectContaining({ title: "Renamed review", channel: "meeting" })));
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Renamed review" })).toBeInTheDocument());
  },
};

/** The one irreversible action is a tier-2 confirm: the exact title must be typed, and it says what goes. */
export const DeletePermanentlyNeedsTheTypedTitle: Story = {
  beforeEach: () => {
    mockDetailApis(buildEngagement());
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Delete permanently" }));
    await userEvent.click(canvas.getByRole("button", { name: "Delete permanently" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "Permanently delete Quarterly review with the regulator?" }));
    await expect(dialog.getByText(/its comments, and its attachments and files/)).toBeInTheDocument();
    const confirm = dialog.getByRole("button", { name: "Delete permanently" });
    await expect(confirm).toBeDisabled();
    await userEvent.type(dialog.getByRole("textbox"), "Quarterly review with the regulator");
    await userEvent.click(confirm);
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(EBASE));
    await waitFor(() => expect(within(document.body).getByText("Engagement permanently deleted.")).toBeInTheDocument());
    // It returns to the list.
    await waitFor(() => expect(canvas.getByTestId("location")).toHaveTextContent(`/projects/${PROJECT_ID}/modules/stakeholders/engagements`));
  },
};

export const LoadFailureShowsAMessage: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockRejectedValue(new ApiError(404, "Engagement not found."));
  },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByText("Engagement not found.")).toBeInTheDocument());
  },
};

export const LightTheme: Story = { ...ShowsFieldsPeopleAndOutcomes };
export const DarkTheme: Story = { ...ShowsFieldsPeopleAndOutcomes, globals: { theme: "dark" } };

/** Links live in the shared Links panel beside the page. */
export const LinksPanelShowsLinks: Story = {
  beforeEach: () => mockDetailApis(buildEngagement()),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getAllByRole("link", { name: "Reports arrive late" }).length).toBeGreaterThan(0));
  },
};
