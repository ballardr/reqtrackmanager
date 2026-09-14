import type { Decorator, Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";
import { page } from "vitest/browser";

import { api } from "../api/client";
import type { Organization, Project, ProjectListItem, ServerSettings, SystemVersion } from "../api/types";
import { ThemeProvider } from "../context/ThemeContext";
import { buildProject, buildUser, withAuth, withRouter } from "../testing/storybook-helpers";
import { Layout } from "./Layout";

const BACKEND_VERSION: SystemVersion = { version: "1.4.0", git_sha: "abc1234", build_date: "2026-08-15T09:00:00Z" };

const SERVER_SETTINGS: ServerSettings = {
  accent_color_hex: "#475569",
  default_logo_file_id: null,
  default_header_title: "ReqTrack Manager",
  default_login_background_file_id: null,
  email_footer_company_name: null,
  email_footer_website: null,
  email_footer_address: null,
  org_label_singular: null,
  org_label_plural: null,
};

const ORG: Organization = {
  id: "org-1", name: "Acme Corp", created_at: "2026-01-01T00:00:00Z", logo_file_id: null,
  default_template_project_id: null, login_background_file_id: null, slug: "acme", is_active: true,
  disabled_at: null, accent_color_hex: null, header_title: null,
  email_footer_company_name: null, email_footer_website: null, email_footer_address: null,
  force_require_change_request_for_approved_links: false,
};

const PROJECT: Project = buildProject({ id: "project-1", organization_id: "org-1" });

/** Routes every `api.get` call Layout's provider tree can make (branding,
 * terminology, favourites probe, notifications) to fixture data by path
 * prefix — Layout composes several providers each with their own fetch, so
 * a single path-matching mock is far more maintainable than one spy per
 * story. */
function mockLayoutApis() {
  spyOn(api, "get").mockImplementation(async (path: string): Promise<unknown> => {
    if (path === "/api/v1/system/branding") return SERVER_SETTINGS;
    if (path === "/api/v1/orgs") return [ORG];
    if (path === `/api/v1/projects/${PROJECT.id}`) return PROJECT;
    if (path === `/api/v1/orgs/${ORG.id}`) return ORG;
    if (path.startsWith("/api/v1/projects?")) return [] as ProjectListItem[];
    if (path === "/api/v1/notifications") return [];
    if (path === "/api/v1/system/version") return BACKEND_VERSION;
    // `useProjectEnabledModules` (module system Phase 3) — Layout's nav
    // rail calls this whenever a project route is active, independently of
    // whether any module is actually registered; found as a real,
    // pre-existing gap (an unhandled promise rejection during the full
    // Storybook suite) while verifying Phase 13's own changes here — fixed
    // in passing rather than left, per this repo's "fix, don't defer" rule.
    if (path.endsWith("/enabled-modules")) return [];
    // Compliance's own `globalNavItems` contribution (compliance-module-
    // plan.md Phase 18, `ComplianceGlobalNavLink.tsx`) fetches this
    // unconditionally whenever a user is logged in, via `Layout.tsx`'s
    // generic module-nav-item mechanism — not something Layout.tsx itself
    // knows or cares about, but this mock intercepts every `api.get` call
    // during the story regardless of which module made it. `false` keeps
    // every existing story's nav-rail assertions unaffected; visibility
    // itself is covered by `ComplianceGlobalNavLink.stories.tsx` instead.
    if (path === "/api/v1/compliance/nav-visibility") return { visible: false };
    throw new Error(`unmocked path in Layout story: ${path}`);
  });
}

const withThemeProvider: Decorator = (Story) => <ThemeProvider>{Story()}</ThemeProvider>;

const meta: Meta<typeof Layout> = {
  title: "Components/Layout",
  component: Layout,
  args: { children: <div>Page content</div> },
  decorators: [withThemeProvider],
};
export default meta;

type Story = StoryObj<typeof Layout>;

export const LoggedOut: Story = {
  decorators: [withAuth(null), withRouter("/login")],
  beforeEach: () => {
    mockLayoutApis();
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Page content")).toBeInTheDocument();
    await expect(canvas.queryByRole("navigation")).not.toBeInTheDocument();
  },
};

export const LoggedInNoProject: Story = {
  decorators: [withAuth(buildUser({ display_name: "Alex Morgan", is_server_admin: false })), withRouter("/projects")],
  beforeEach: () => {
    mockLayoutApis();
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("navigation")).toBeInTheDocument();
    await expect(canvas.queryByText("Project")).not.toBeInTheDocument();
    await expect(canvas.queryByText("Administration")).not.toBeInTheDocument();
    // The only path to org administration for a non-server-admin (2026-08
    // UX audit finding: /orgs previously had no rail entry at all).
    await expect(canvas.getByRole("link", { name: "My organisations" })).toBeInTheDocument();
  },
};

export const LoggedInWithProjectRoute: Story = {
  decorators: [withAuth(buildUser({ display_name: "Alex Morgan" })), withRouter(`/projects/${PROJECT.id}/requirements`)],
  beforeEach: () => {
    mockLayoutApis();
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Project")).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "Requirements" })).toHaveClass("active");
  },
};

export const ServerAdmin: Story = {
  decorators: [withAuth(buildUser({ display_name: "Sam Admin", is_server_admin: true })), withRouter("/projects")],
  beforeEach: () => {
    mockLayoutApis();
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Administration")).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: /Server management/ })).toBeInTheDocument();
  },
};

/** The nav rail's build-identity footer (2026-08 UX audit follow-up: "a
 * way to see the version and date of the frontend and backend in the
 * UI") — the frontend's own build constants (unset in a Storybook build,
 * so `version.ts`'s documented "dev"/"unknown" fallback applies) plus the
 * backend's, fetched from `GET /api/v1/system/version` and rendered once
 * it resolves. Hidden entirely when the rail is collapsed to icons-only,
 * same as every other rail label — not asserted here since that's
 * `useUiPreference`'s own default-false state, exercised by the collapse
 * button elsewhere, not this story's concern. */
export const ShowsVersionFooter: Story = {
  decorators: [withAuth(buildUser({ display_name: "Alex Morgan", is_server_admin: false })), withRouter("/projects")],
  beforeEach: () => {
    mockLayoutApis();
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("App vdev")).toBeInTheDocument();
    await expect(canvas.getByText("API v1.4.0")).toBeInTheDocument();
  },
};

/** Regression pin for a real bug: the collapse/expand toggle is
 * `position: fixed`, placed independently of its parent's flow position via
 * a `left` CSS var that changes with collapse state — so `Tooltip`'s
 * default in-flow wrapping span (sized to fit an out-of-flow child, i.e.
 * collapsing to zero size) landed nowhere near the button, and the bubble
 * showed up near the *collapsed* rail position even while expanded. Fixed
 * by giving the wrapper the same fixed placement as the button (`Tooltip`'s
 * `className`/`style` props). This asserts the bubble is actually centred
 * on the button's real on-screen box, not a hardcoded pixel value. */
export const ToggleTooltipTracksButtonPosition: Story = {
  decorators: [withAuth(buildUser({ display_name: "Alex Morgan" })), withRouter("/projects")],
  beforeEach: () => {
    mockLayoutApis();
  },
  play: async ({ canvasElement }) => {
    await page.viewport(1280, 800);
    const canvas = within(canvasElement);
    const toggle = await waitFor(() => canvas.getByRole("button", { name: "Collapse navigation" }));
    await userEvent.hover(toggle);
    // Several other rail/header controls also render their own (hidden)
    // tooltip bubbles, so this must match by name, not just role.
    const bubble = await waitFor(() =>
      within(document.body).getByRole("tooltip", { name: "Collapse navigation", hidden: true })
    );
    await waitFor(() => expect(bubble).toHaveStyle({ opacity: "1" }));
    const buttonRect = toggle.getBoundingClientRect();
    const bubbleRect = bubble.getBoundingClientRect();
    const buttonCenterX = buttonRect.left + buttonRect.width / 2;
    const bubbleCenterX = bubbleRect.left + bubbleRect.width / 2;
    await expect(Math.abs(bubbleCenterX - buttonCenterX)).toBeLessThan(2);
  },
};

/** Regression pin for a second real bug found alongside the one above:
 * below theme.css's 860px nav-rail breakpoint, CSS force-collapses the rail
 * to icon-only regardless of the user's own (default-expanded)
 * `nav_rail_collapsed` preference — but `NavRailLink` only wrapped its link
 * in a `Tooltip` when that JS preference was `true`, so a narrow window
 * hid every link's text with no tooltip to replace it. Fixed via
 * `Layout.tsx`'s `railIconOnly` (preference OR `useNarrowViewport`). */
export const NarrowViewportShowsLinkTooltips: Story = {
  decorators: [withAuth(buildUser({ display_name: "Alex Morgan" })), withRouter(`/projects/${PROJECT.id}/requirements`)],
  beforeEach: () => {
    mockLayoutApis();
  },
  play: async ({ canvasElement }) => {
    await page.viewport(700, 800);
    const canvas = within(canvasElement);
    // The `matchMedia` "change" listener that flips `useNarrowViewport`'s
    // state fires asynchronously relative to `page.viewport()` resolving
    // (see FilterPanel.stories.tsx's `MobileCollapsedByDefault` for the
    // same caveat) — wait for the rail to actually reflect icon-only mode.
    await waitFor(() => expect(canvas.getByRole("navigation")).toHaveClass("nav-rail-icons"));
    const link = canvas.getByRole("link", { name: "Requirements" });
    await userEvent.hover(link);
    // Several other rail/header controls also render their own (hidden)
    // tooltip bubbles, so this must match by name, not just role.
    const bubble = await waitFor(() =>
      within(document.body).getByRole("tooltip", { name: "Requirements", hidden: true })
    );
    await waitFor(() => expect(bubble).toHaveStyle({ opacity: "1" }));
  },
};

export const LightTheme: Story = { ...LoggedInWithProjectRoute, globals: { theme: "light" } };
export const DarkTheme: Story = { ...LoggedInWithProjectRoute, globals: { theme: "dark" } };
