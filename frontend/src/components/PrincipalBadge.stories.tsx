import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, within } from "storybook/test";

import type { Principal } from "../api/types";
import { expectStressStable, stressText } from "../testing/stressFixtures";
import { TextStress } from "../testing/TextStress";
import { PrincipalBadge } from "./PrincipalBadge";

const meta: Meta<typeof PrincipalBadge> = { title: "Components/PrincipalBadge", component: PrincipalBadge };
export default meta;

type Story = StoryObj<typeof PrincipalBadge>;

/** A user is just their name, with no kind tag. */
export const User: Story = {
  args: { principal: { type: "user", id: "u1", label: "Alex Morgan", member_count: null, exists: true } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Alex Morgan")).toBeInTheDocument();
    await expect(canvas.queryByText(/group/i)).not.toBeInTheDocument();
  },
};

/** An imported person (a stand-in for someone named in an import bundle) carries an Imported badge. */
export const ImportedPerson: Story = {
  args: { principal: { type: "user", id: "u2", label: "Alex Morgan", member_count: null, exists: true, imported: true } },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("Imported")).toBeInTheDocument();
  },
};

/**
 * A group is its icon and name, with no kind pill: the kind and member count are hidden text before the name (the
 * accessible name) and a tooltip on hover.
 */
export const OrgGroup: Story = {
  args: { principal: { type: "org_group", id: "g1", label: "Platform team", member_count: 4, exists: true } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Platform team")).toBeInTheDocument();
    await expect(canvas.getByText("Organisation group, 4 members")).toHaveClass("sr-only");
    await expect(canvasElement.querySelector(".badge")).toBeNull();
    await userEvent.hover(canvas.getByText("Platform team"));
    await expect(await within(document.body).findByRole("tooltip")).toHaveTextContent("Organisation group, 4 members");
  },
};

export const ProjectGroupWithOneMember: Story = {
  args: { principal: { type: "project_group", id: "pg1", label: "Release board", member_count: 1, exists: true } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Project group, 1 member")).toHaveClass("sr-only");
    await expect(canvasElement.querySelector(".badge")).toBeNull();
  },
};

/** A history row can still name a group that has since been deleted; it keeps a visible Deleted marker. */
export const DeletedGroup: Story = {
  args: { principal: { type: "org_group", id: "g9", label: "Retired group", member_count: null, exists: false } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Deleted")).toBeInTheDocument();
    await expect(canvas.getByText("Organisation group, deleted")).toHaveClass("sr-only");
  },
};

export const Empty: Story = {
  args: { principal: null },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("Unassigned")).toBeInTheDocument();
  },
};

export const DarkTheme: Story = { ...OrgGroup, globals: { theme: "dark" } };

/** A service user carries the Service badge, with a tooltip saying what that is. */
export const ServiceUser: Story = {
  args: { principal: { type: "user", id: "u3", label: "Build agent", member_count: null, exists: true, service: true } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Build agent")).toBeInTheDocument();
    await expect(canvas.getByText("Service")).toBeInTheDocument();
  },
};

const GROUP: Principal = { type: "org_group", id: "g1", label: "Platform team", member_count: 4, exists: true };
const PERSON: Principal = { type: "user", id: "u1", label: "Alex Morgan", member_count: null, exists: true };

/** A group owner is exactly as tall as a user owner, and a long name or an Imported badge never moves the row's control. */
export const LongText: Story = {
  render: () => (
    <TextStress
      width={520}
      render={(long) => (
        <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: 8 }}>
          {[
            { ...PERSON, label: stressText(long, "Alex Morgan") },
            { ...GROUP, label: stressText(long, "Platform team") },
            { ...GROUP, type: "project_group" as const, label: stressText(long, "Release board", "word"), imported: true },
          ].map((principal) => (
            <li key={principal.type + principal.label} data-stress-row style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <span style={{ flex: "1 1 0", minWidth: 0 }}><PrincipalBadge principal={principal} /></span>
              <button className="btn" style={{ flex: "none" }}>Edit</button>
            </li>
          ))}
        </ul>
      )}
    />
  ),
  play: async ({ canvasElement }) => {
    await expectStressStable(canvasElement);
    const rows = Array.from(canvasElement.querySelectorAll<HTMLElement>('[data-stress="long"] li'));
    const heights = rows.map((row) => Math.round(row.getBoundingClientRect().height));
    await expect(new Set(heights).size).toBe(1);
  },
};
