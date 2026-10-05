import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, within } from "storybook/test";

import type { OrgUser } from "../../api/types";
import { RecordField, RecordFieldGroup, RecordPersonField, VersionHistoryTable } from "./RecordDetailParts";

const ORG_USERS: OrgUser[] = [
  {
    user_id: "user-2", email: "jamie.lee@example.com", display_name: "Jamie Lee", is_active: true, is_archived: false,
    roles: ["member"], display_name_locked: false, last_login_at: null, is_2fa_enabled: false, module_roles: [], custom_roles: [],
  },
];

const meta: Meta = { title: "Modules/Stakeholders/RecordDetailParts" };
export default meta;

type Story = StoryObj;

export const FieldKeepsLineBreaks: Story = {
  render: () => <RecordField label="Goals" value={"First goal\nSecond goal"} />,
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("Goals")).toBeInTheDocument();
    await expect(within(canvasElement).getByText(/First goal/)).toHaveStyle({ whiteSpace: "pre-wrap" });
  },
};

export const FieldGroupLabelsArbitraryContent: Story = {
  render: () => (
    <RecordFieldGroup label="Engagement">
      <span>Target cadence: Quarterly</span>
    </RecordFieldGroup>
  ),
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("Engagement")).toBeInTheDocument();
    await expect(within(canvasElement).getByText("Target cadence: Quarterly")).toBeInTheDocument();
  },
};

export const PersonFieldEditableShowsAPicker: Story = {
  render: () => (
    <RecordPersonField label="Owner" ariaLabel="Record owner" userId={null} orgUsers={ORG_USERS} readOnly={false} onChange={fn()} />
  ),
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByLabelText("Record owner")).toBeInTheDocument();
  },
};

export const PersonFieldReadOnlyShowsTheName: Story = {
  render: () => (
    <RecordPersonField label="Owner" ariaLabel="Record owner" userId="user-2" orgUsers={ORG_USERS} readOnly onChange={fn()} />
  ),
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("Jamie Lee")).toBeInTheDocument();
    await expect(within(canvasElement).queryByLabelText("Record owner")).not.toBeInTheDocument();
  },
};

export const PersonFieldReadOnlyUnassigned: Story = {
  render: () => (
    <RecordPersonField label="Owner" ariaLabel="Record owner" userId={null} orgUsers={ORG_USERS} readOnly onChange={fn()} />
  ),
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("Unassigned")).toBeInTheDocument();
  },
};

const VERSIONS = [
  { id: "v1", version_number: 1, valid_from: "2026-01-10T09:00:00Z", change_note: "Initial creation.", status: "Draft" },
  { id: "v2", version_number: 2, valid_from: "2026-01-11T09:00:00Z", change_note: "", status: "Active" },
];

export const VersionHistoryNewestFirstWithKindColumns: Story = {
  render: () => <VersionHistoryTable versions={VERSIONS} columns={[{ header: "Status", render: (v) => v.status }]} />,
  play: async ({ canvasElement }) => {
    const rows = within(canvasElement).getAllByRole("row");
    // header + newest (v2) + oldest (v1)
    await expect(within(rows[1]).getByText("Active")).toBeInTheDocument();
    await expect(within(rows[2]).getByText("Initial creation.")).toBeInTheDocument();
    await expect(within(rows[1]).getByText("—")).toBeInTheDocument(); // an empty change note
  },
};

export const VersionHistoryHiddenForASingleVersion: Story = {
  render: () => <VersionHistoryTable versions={VERSIONS.slice(0, 1)} columns={[]} />,
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("heading", { name: "Version history" })).not.toBeInTheDocument();
  },
};

export const DarkTheme: Story = { ...VersionHistoryNewestFirstWithKindColumns, globals: { theme: "dark" } };
