import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import { AuthContext } from "../context/AuthContextValue";
import { applyUiPreferencePatch } from "../context/uiPreferencePatch";
import { buildUser } from "../testing/storybook-helpers";
import { CollapsibleSection } from "./CollapsibleSection";

/** `useUiPreference` (which CollapsibleSection uses to remember collapsed
 * state) reads/writes through `useAuth()`, so this wraps stories in a real,
 * stateful `AuthContext.Provider` — not the no-op stub `withAuth` defaults
 * to — so toggling the section is actually observable across a re-render,
 * matching the server-synced preference it stands in for. */
function Interactive({ variant = "card" as "card" | "plain", defaultCollapsed = false, summary = undefined as string | undefined, marked = false, forceOpen = false }) {
  const [user, setUser] = useState(buildUser({ ui_preferences: {} }));
  return (
    <AuthContext.Provider
      value={{
        user,
        loading: false,
        login: async () => {
          throw new Error("not mocked");
        },
        signup: async () => {
          throw new Error("not mocked");
        },
        verify2fa: async () => {
          throw new Error("not mocked");
        },
        logout: () => {},
        refreshUser: async () => {},
        setUiPreference: (key, value) =>
          setUser((u) => ({ ...u, ui_preferences: applyUiPreferencePatch(u.ui_preferences, { [key]: value }) })),
        setUiPreferences: async (patch) =>
          setUser((u) => ({ ...u, ui_preferences: applyUiPreferencePatch(u.ui_preferences, patch) })),
      }}
    >
      <CollapsibleSection sectionKey="storyExample" title="Personal Access Tokens" variant={variant} defaultCollapsed={defaultCollapsed}
        summary={summary} marked={marked} forceOpen={forceOpen}>
        <p style={{ margin: 0 }}>Section content goes here.</p>
      </CollapsibleSection>
    </AuthContext.Provider>
  );
}

const meta: Meta<typeof Interactive> = {
  title: "Components/CollapsibleSection",
  component: Interactive,
};
export default meta;

type Story = StoryObj<typeof Interactive>;

export const ExpandedCardVariant: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Section content goes here.")).toBeInTheDocument();
    const header = canvas.getByRole("button", { name: "Personal Access Tokens section" });
    await expect(header).toHaveAttribute("aria-expanded", "true");
    await userEvent.click(header);
    await expect(canvas.queryByText("Section content goes here.")).not.toBeInTheDocument();
  },
};

export const CollapsedByDefault: Story = {
  args: { defaultCollapsed: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByText("Section content goes here.")).not.toBeInTheDocument();
    const header = canvas.getByRole("button", { name: "Personal Access Tokens section" });
    await expect(header).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(header);
    await expect(canvas.getByText("Section content goes here.")).toBeInTheDocument();
  },
};

export const PlainVariant: Story = {
  args: { variant: "plain" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Section content goes here.")).toBeInTheDocument();
  },
};

/** A closed bar can say what it holds: a pill the bar is described by, and an accent edge. */
export const ClosedBarShowsItsSummary: Story = {
  args: { variant: "plain", defaultCollapsed: true, summary: "2 changed", marked: true },
  play: async ({ canvasElement }) => {
    const bar = within(canvasElement).getByRole("button", { name: "Personal Access Tokens section" });
    await expect(bar).toHaveAccessibleDescription("2 changed");
    await expect(bar).toHaveClass("collapsible-bar--marked");
  },
};

/** A section held open stays open, whatever was stored, and its toggle is inert. */
export const ForcedOpenIgnoresTheStoredChoice: Story = {
  args: { variant: "plain", defaultCollapsed: true, summary: "1 problem", forceOpen: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const bar = canvas.getByRole("button", { name: "Personal Access Tokens section" });
    await expect(bar).toHaveAttribute("aria-expanded", "true");
    await expect(bar).toHaveAttribute("aria-disabled", "true");
    await userEvent.click(bar);
    await expect(canvas.getByText("Section content goes here.")).toBeVisible();
  },
};

export const LightTheme: Story = { globals: { theme: "light" } };
export const DarkTheme: Story = { globals: { theme: "dark" } };
