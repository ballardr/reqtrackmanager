import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import type { Permission } from "../api/types";
import { buildUser, withAuth } from "../testing/storybook-helpers";
import { PermissionPicker } from "./PermissionPicker";

const PERMISSIONS: Permission[] = [
  { key: "requirement:view:", label: "requirement — view", artefact_type: "requirement", level: "view", subtype: null },
  {
    key: "requirement:propose_create:",
    label: "requirement — propose_create",
    artefact_type: "requirement",
    level: "propose_create",
    subtype: null,
  },
  { key: "requirement:manage:", label: "requirement — manage", artefact_type: "requirement", level: "manage", subtype: null },
  { key: "decision:view:", label: "decision — view", artefact_type: "decision", level: "view", subtype: null },
  {
    key: "decision:approve_baseline:",
    label: "decision — approve_baseline",
    artefact_type: "decision",
    level: "approve_baseline",
    subtype: null,
  },
  {
    key: "decision:approve_baseline:Architecture",
    label: "decision — approve_baseline (Architecture)",
    artefact_type: "decision",
    level: "approve_baseline",
    subtype: "Architecture",
  },
  { key: "grant_roles", label: "Grant Roles", artefact_type: null, level: null, subtype: null },
  { key: "manage_members", label: "Manage Members", artefact_type: null, level: null, subtype: null },
];

const meta: Meta<typeof PermissionPicker> = {
  title: "Components/PermissionPicker",
  component: PermissionPicker,
  // Each group renders as a `CollapsibleSection`, whose remembered
  // collapsed state reads/writes through `useAuth()` (`useUiPreference`) —
  // same reasoning as `CollapsibleSection.stories.tsx`'s own decorator.
  decorators: [withAuth(buildUser())],
  args: {
    permissions: PERMISSIONS,
    selected: ["requirement:view:", "grant_roles"],
    onChange: fn(),
  },
};
export default meta;

type Story = StoryObj<typeof PermissionPicker>;

/** Options are grouped by artefact type (each its own collapsible section),
 * with the short administrative list (grant_roles, manage_members, ...)
 * grouped last under its own "Administrative" heading — mirrors
 * `get_all_permissions`'s own server-side ordering. */
export const GroupedByArtefactType: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("checkbox", { name: "requirement — view" })).toBeChecked();
    await expect(canvas.getByRole("checkbox", { name: "decision — view" })).not.toBeChecked();
    await expect(canvas.getByRole("checkbox", { name: "Grant Roles" })).toBeChecked();
  },
};

/** A sub-type-scoped atom (e.g. "decision — approve_baseline (Architecture)")
 * renders as its own independent checkbox alongside the wildcard
 * ("decision — approve_baseline") — both are real, separately-toggleable
 * options, not a nested/dependent pair. */
export const SubtypeScopedAtomIsItsOwnOption: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("checkbox", { name: "decision — approve_baseline" })).toBeInTheDocument();
    await expect(canvas.getByRole("checkbox", { name: "decision — approve_baseline (Architecture)" })).toBeInTheDocument();
  },
};

/** Toggling a checkbox calls `onChange` with the full next selection —
 * this component holds no state of its own, matching every other
 * controlled picker in this codebase. */
export const TogglingCallsOnChangeWithNextSelection: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("checkbox", { name: "decision — view" }));
    await expect(args.onChange).toHaveBeenCalledWith(["requirement:view:", "grant_roles", "decision:view:"]);
  },
};

/** An empty vocabulary (e.g. still loading) shows a plain text hint
 * instead of an empty set of groups. */
export const EmptyVocabularyShowsHint: Story = {
  args: { permissions: [], selected: [] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("No permissions available.")).toBeInTheDocument();
  },
};

/** `disabled` renders every checkbox non-interactive — used while a
 * create/update request is in flight. */
export const Disabled: Story = {
  args: { disabled: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("checkbox", { name: "requirement — view" })).toBeDisabled();
  },
};

export const LightTheme: Story = { globals: { theme: "light" } };
export const DarkTheme: Story = { globals: { theme: "dark" } };
