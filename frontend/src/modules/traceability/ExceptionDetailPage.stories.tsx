import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildApprovalStatus } from "../../testing/approvalSeparationFixtures";
import { buildUser, withRouter, withStatefulAuth, withToast } from "../../testing/storybook-helpers";
import { ExceptionDetailPage } from "./ExceptionDetailPage";
import { buildException, EXCEPTION_PROJECT_ID } from "./exceptionFixtures";
import type { TraceabilityException } from "./types";

const BASE = `/api/v1/projects/${EXCEPTION_PROJECT_ID}/modules/traceability/exceptions/tex-1`;

function mockApis(current: TraceabilityException, selfApproved = false) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === BASE) return current;
    if (path.includes("/approval-separation/status/traceability_exception/")) {
      return buildApprovalStatus({ self_approved: selfApproved, approved_by_name: selfApproved ? "Alex Morgan" : null });
    }
    if (path.endsWith(`/projects/${EXCEPTION_PROJECT_ID}`)) return { id: EXCEPTION_PROJECT_ID, organization_id: "org-1" };
    if (path.endsWith("/comments") || path.endsWith("/files")) return [];
    throw new Error(`Unmocked GET: ${path}`);
  });
}

const meta: Meta<typeof ExceptionDetailPage> = {
  title: "Modules/Traceability/ExceptionDetailPage",
  component: ExceptionDetailPage,
  decorators: [
    withStatefulAuth(buildUser({ id: "user-1", display_name: "Alex Morgan", ui_preferences: {} })),
    withRouter(
      `/projects/${EXCEPTION_PROJECT_ID}/modules/traceability/exceptions/tex-1`,
      "/projects/:projectId/modules/traceability/exceptions/:exceptionId",
    ),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof ExceptionDetailPage>;

/** The record, rule, reason, cover, people, dates and decision, with no control that changes the exception. */
export const ShowsAnApprovedException: Story = {
  beforeEach: () => { mockApis(buildException()); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Exception to Requirements are verified" })).toBeInTheDocument());
    await expect(canvas.getByText("TEX-001")).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "SW-PERF-001 Respond within one second" })).toHaveAttribute(
      "href", `/projects/${EXCEPTION_PROJECT_ID}/requirements/req-1`,
    );
    await expect(canvas.getAllByText("Covering").length).toBeGreaterThan(0);
    await expect(canvas.getByText("2027-06-30")).toBeInTheDocument();
    await expect(canvas.getByText("Accepted for this release.")).toBeInTheDocument();
    await expect(canvas.getByText(/Sam Whitfield/)).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: /Approve|Reject|Revoke|Next step/ })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("region", { name: "Links" })).not.toBeInTheDocument();
  },
};

/** An approval given by the person who submitted the exception is marked on the record. */
export const MarksASelfApproval: Story = {
  beforeEach: () => { mockApis(buildException(), true); },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("Self-approved")).toBeInTheDocument();
  },
};

/** A changed rule, an enforced one and a removed record are each stated. */
export const FlagsWhatNeedsAttention: Story = {
  beforeEach: () => {
    mockApis(buildException({
      rule_changed: true, needs_organisation_approval: true, covers: false, no_cover_reason: "needs_organisation_approval",
      record: { artefact_type: "requirement", artefact_type_label: "Requirement", id: "req-1", code: "", label: "", removed: true },
    }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("Rule changed since approval")).toHaveClass("badge--warning");
    await expect(canvas.getAllByText("Needs organisation approval").length).toBeGreaterThan(0);
    await expect(canvas.getByText(/only an organisation-level approver/)).toBeInTheDocument();
    await expect(canvas.getByText("Removed record")).toBeInTheDocument();
  },
};

export const NotFound: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockRejectedValue(new Error("Traceability exception not found."));
  },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("Traceability exception not found.")).toBeInTheDocument();
  },
};
