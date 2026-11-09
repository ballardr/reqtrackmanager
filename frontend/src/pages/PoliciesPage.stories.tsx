import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import { buildMemberPolicy, buildPolicyBody, buildPublicPolicy, buildUser, withAuth, withRouter } from "../testing/storybook-helpers";
import { PoliciesPage } from "./PoliciesPage";

const PRIVACY = buildPublicPolicy({ id: "p1", key: "privacy", title: "Privacy policy" });
const DATA = buildPublicPolicy({ id: "p2", key: "data", title: "Data policy", effective_from: null, version: 1, body: buildPolicyBody("Data is kept for seven years.") });

function mockPolicies(...policies: ReturnType<typeof buildPublicPolicy>[]) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === "/api/v1/public/policies") return policies.map(({ body, ...summary }) => { void body; return summary; });
    return policies.find((p) => path.endsWith(`/${p.id}`)) ?? Promise.reject(new Error("not found"));
  });
}

/** The public Policies page: the published policies, one at a time. */
const meta: Meta<typeof PoliciesPage> = { title: "Pages/PoliciesPage", component: PoliciesPage };
export default meta;

type Story = StoryObj<typeof PoliciesPage>;

/** With none published the page does not exist: it redirects to the front page and shows nothing. */
export const NoPoliciesPublished: Story = {
  decorators: [withRouter("/policies", "/policies/:policyId?")],
  beforeEach: () => mockPolicies(),
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(api.get).toHaveBeenCalledWith("/api/v1/public/policies"));
    await expect(within(canvasElement).queryByRole("heading", { name: "Policies" })).not.toBeInTheDocument();
    await expect(within(canvasElement).queryByText("No policy has been published yet.")).not.toBeInTheDocument();
  },
};

/** One policy shows its text, effective date and version without any other policy in the menu. */
export const OnePolicy: Story = {
  decorators: [withRouter("/policies", "/policies/:policyId?")],
  beforeEach: () => mockPolicies(PRIVACY),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("heading", { name: "Privacy policy", level: 2 })).toBeInTheDocument();
    await expect(canvas.getByText("We keep only what the service needs.")).toBeInTheDocument();
    await expect(canvas.getByText(/Effective from/)).toBeInTheDocument();
    await expect(canvas.getByText(/Version 2, published/)).toBeInTheDocument();
  },
};

/** Several policies list in the menu, the first is shown, and choosing another shows it. */
export const SeveralPoliciesSwitchFromTheMenu: Story = {
  decorators: [withRouter("/policies", "/policies/:policyId?")],
  beforeEach: () => mockPolicies(PRIVACY, DATA),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("We keep only what the service needs.")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("link", { name: "Data policy" }));
    await expect(await canvas.findByText("Data is kept for seven years.")).toBeInTheDocument();
  },
};

/** An address naming a policy that is not published shows the first policy, so the page never dead-ends. */
export const UnknownAddressShowsTheFirstPolicy: Story = {
  decorators: [withRouter("/policies/p9", "/policies/:policyId?")],
  beforeEach: () => mockPolicies(PRIVACY),
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("We keep only what the service needs.")).toBeInTheDocument();
  },
};

const ACCESS = buildMemberPolicy({ id: "o1", title: "Access policy" });
const CONFIDENTIALITY = buildMemberPolicy({ id: "o2", title: "Confidentiality agreement", body: buildPolicyBody("Keep client information private.") });
const OTHER_ORG = buildMemberPolicy({ id: "o3", organization_id: "org-2", organization_name: "Globex", title: "Code of conduct" });

function mockWithMember(server: ReturnType<typeof buildPublicPolicy>[], member: ReturnType<typeof buildMemberPolicy>[]) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === "/api/v1/public/policies") return server.map(({ body, ...summary }) => { void body; return summary; });
    if (path === "/api/v1/policies/mine") return member.map(({ body, ...summary }) => { void body; return summary; });
    const found = [...server, ...member].find((p) => path.endsWith(`/${p.id}`));
    return found ?? Promise.reject(new Error("not found"));
  });
}

/** A signed-in member sees the server's policies, then their organisation's under its name; choosing one shows its text. */
export const MemberSeesOrganisationPoliciesBesideTheServers: Story = {
  decorators: [withRouter("/policies", "/policies/:policyId?"), withAuth(buildUser())],
  beforeEach: () => mockWithMember([PRIVACY], [ACCESS, CONFIDENTIALITY, OTHER_ORG]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("link", { name: "Privacy policy" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: /Acme/ })).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "Globex: Code of conduct" })).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: /Acme/ }));
    await userEvent.click(await canvas.findByRole("link", { name: "Confidentiality agreement" }));
    await expect(await canvas.findByText("Keep client information private.")).toBeInTheDocument();
    await expect(canvas.getByText(/Acme\./)).toBeInTheDocument();
    await expect(api.get).toHaveBeenCalledWith("/api/v1/policies/mine/o2");
  },
};

/** A member of an organisation with policies but no server policy still gets the page. */
export const OnlyOrganisationPolicies: Story = {
  decorators: [withRouter("/policies", "/policies/:policyId?"), withAuth(buildUser())],
  beforeEach: () => mockWithMember([], [ACCESS]),
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByRole("heading", { name: "Access policy", level: 2 })).toBeInTheDocument();
  },
};

/** A signed-out visitor never reads the member endpoint. */
export const SignedOutNeverReadsOrganisationPolicies: Story = {
  decorators: [withRouter("/policies", "/policies/:policyId?"), withAuth(null)],
  beforeEach: () => mockWithMember([PRIVACY], [ACCESS]),
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByRole("heading", { name: "Privacy policy", level: 2 });
    await expect(api.get).not.toHaveBeenCalledWith("/api/v1/policies/mine");
  },
};
