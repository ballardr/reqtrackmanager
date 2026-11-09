import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, within } from "storybook/test";

import { api } from "../api/client";
import { buildPolicyBody, buildPublicPolicy, withRouter } from "../testing/storybook-helpers";
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

/** With none published the page says so. */
export const NoPoliciesPublished: Story = {
  decorators: [withRouter("/policies", "/policies/:policyId?")],
  beforeEach: () => mockPolicies(),
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("No policy has been published yet.")).toBeInTheDocument();
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
