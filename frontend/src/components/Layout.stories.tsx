import type { Decorator, Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";
import { page } from "vitest/browser";

import { api } from "../api/client";
import type { ClientConfig, ModuleNavEntry, Organization, Project, ProjectListItem, ServerSettings, SystemVersion } from "../api/types";
import { ThemeProvider } from "../context/ThemeContext";
import { buildProject, buildUser, withAuth, withRouter } from "../testing/storybook-helpers";
import { Layout } from "./Layout";

const DEFAULT_CLIENT_CONFIG: ClientConfig = { help_enabled: true, help_url: "https://docs.example.com/" };

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
  code: "ACME", project_code_policy: { kind: "alphanumeric", min_length: 2, max_length: 6, assignment: "auto" }, enforce_code_everywhere: false,
  force_require_change_request_for_approved_links: false,
  allow_ai_approvals: false,
};

const PROJECT: Project = buildProject({ id: "project-1", organization_id: "org-1" });

/** Routes every `api.get` call Layout's provider tree can make (branding,
 * terminology, favourites probe, notifications) to fixture data by path
 * prefix — Layout composes several providers each with their own fetch, so
 * a single path-matching mock is far more maintainable than one spy per
 * story. */
function mockLayoutApis(clientConfig: ClientConfig = DEFAULT_CLIENT_CONFIG, enabledModules: ModuleNavEntry[] = []) {
  spyOn(api, "get").mockImplementation(async (path: string): Promise<unknown> => {
    if (path === "/api/v1/system/branding") return SERVER_SETTINGS;
    if (path === "/api/v1/orgs") return [ORG];
    if (path === `/api/v1/projects/${PROJECT.id}`) return PROJECT;
    if (path === `/api/v1/orgs/${ORG.id}`) return ORG;
    if (path.startsWith("/api/v1/projects?")) return [] as ProjectListItem[];
    if (path === "/api/v1/notifications") return [];
    if (path === "/api/v1/system/version") return BACKEND_VERSION;
    if (path === "/api/v1/system/client-config") return clientConfig;
    // `useProjectEnabledModules` — Layout's nav
    // rail calls this whenever a project route is active, independently of
    // whether any module is actually registered; found as a real,
    // pre-existing gap (an unhandled promise rejection during the full
    // Storybook suite) while verifying changes here — fixed
    // in passing rather than left, per this repo's "fix, don't defer" rule.
    if (path.endsWith("/enabled-modules")) return enabledModules;
    // Compliance's own `globalNavItems` contribution (`ComplianceGlobalNavLink.tsx`) fetches this
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
    // The only path to org administration for a non-server-admin.
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

/** The nav rail's build-identity footer — the frontend's own build constants (unset in a Storybook build,
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

/** The header Help icon is an external link to the operator-configured URL
 * (`HELP_URL`), opening in a new tab. */
export const HelpLinkOpensConfiguredUrl: Story = {
  decorators: [withAuth(buildUser({ display_name: "Alex Morgan", is_server_admin: false })), withRouter("/projects")],
  beforeEach: () => {
    mockLayoutApis();
  },
  play: async ({ canvasElement }) => {
    const link = await within(canvasElement).findByRole("link", { name: "Help (opens in a new tab)" });
    await expect(link).toHaveAttribute("href", "https://docs.example.com/");
    await expect(link).toHaveAttribute("target", "_blank");
    await expect(link).toHaveAttribute("rel", "noopener noreferrer");
  },
};

/** `HELP_ENABLED=false` removes the Help icon entirely. */
export const HelpLinkHiddenWhenDisabled: Story = {
  decorators: [withAuth(buildUser({ display_name: "Alex Morgan", is_server_admin: false })), withRouter("/projects")],
  beforeEach: () => {
    mockLayoutApis({ help_enabled: false, help_url: "https://docs.example.com/" });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByText("API v1.4.0");
    await expect(canvas.queryByRole("link", { name: /^Help/ })).not.toBeInTheDocument();
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

/** A module with five nav entries, one per sub-component, as Context & Strategy declares them. */
function subComponentModule(disabled: string[]): ModuleNavEntry {
  const entry = (nav_label: string, path: string, sub_component: string) => ({
    nav_label, nav_path: `/projects/${PROJECT.id}/modules/demo/${path}`, nav_icon: "puzzle", sub_component,
  });
  return {
    module_key: "demo", name: "Demo module", disabled_sub_components: disabled,
    frontend_manifest: {
      tier: "installed", nav_label: "Alpha", nav_path: `/projects/${PROJECT.id}/modules/demo/alpha`, nav_icon: "puzzle",
      nav_sub_component: "alpha", frame_url: null, remote_entry_url: null, exposed_module: null,
      additional_nav_entries: [entry("Beta", "beta", "beta"), entry("Gamma", "gamma", "gamma")],
    },
  };
}

/** An entry whose sub-component is off for the project is not in the rail, and History and Project admin
 * come last, after the module's entries. */
export const HidesNavEntriesOfDisabledSubComponents: Story = {
  decorators: [withAuth(buildUser({ display_name: "Alex Morgan" })), withRouter(`/projects/${PROJECT.id}/requirements`)],
  beforeEach: () => {
    mockLayoutApis(DEFAULT_CLIENT_CONFIG, [subComponentModule(["beta"])]);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("link", { name: "Alpha" });
    await expect(canvas.getByRole("link", { name: "Gamma" })).toBeInTheDocument();
    await expect(canvas.queryByRole("link", { name: "Beta" })).not.toBeInTheDocument();
    const names = canvas.getAllByRole("link").map((link) => link.getAttribute("aria-label") ?? link.textContent);
    const order = ["Requirements due for review", "Alpha", "Gamma", "Project history", "Project admin"].map((name) => names.indexOf(name));
    await expect(order.every((index) => index >= 0)).toBe(true);
    await expect(order).toEqual([...order].sort((a, b) => a - b));
  },
};

/** The primary entry hides by the same rule. */
export const HidesPrimaryNavEntryOfDisabledSubComponent: Story = {
  ...HidesNavEntriesOfDisabledSubComponents,
  beforeEach: () => {
    mockLayoutApis(DEFAULT_CLIENT_CONFIG, [subComponentModule(["alpha"])]);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("link", { name: "Beta" });
    await expect(canvas.queryByRole("link", { name: "Alpha" })).not.toBeInTheDocument();
  },
};

/** 40 modules' worth of entries: the item list scrolls inside the rail, below the collapse toggle, so the
 * scrollbar and the toggle never overlap (the collapsed rail is covered by the Playwright spec). */
function longRailModules(): ModuleNavEntry[] {
  return Array.from({ length: 40 }, (_, i) => ({
    module_key: `m${i}`, name: `Module ${i}`,
    frontend_manifest: {
      tier: "installed" as const, nav_label: `Module entry ${i}`, nav_path: `/projects/${PROJECT.id}/modules/m${i}/x`,
      nav_icon: "puzzle", frame_url: null, remote_entry_url: null, exposed_module: null,
    },
  }));
}

export const LongRailScrollbarClearsToggle: Story = {
  decorators: [withAuth(buildUser({ display_name: "Alex Morgan" })), withRouter(`/projects/${PROJECT.id}/requirements`)],
  beforeEach: () => {
    mockLayoutApis(DEFAULT_CLIENT_CONFIG, longRailModules());
  },
  play: async ({ canvasElement }) => {
    await page.viewport(1280, 700);
    const canvas = within(canvasElement);
    await canvas.findByRole("link", { name: "Module entry 39" });
    const scroll = canvasElement.querySelector<HTMLElement>(".nav-rail-scroll")!;
    await expect(scroll.scrollHeight).toBeGreaterThan(scroll.clientHeight);
    const rail = canvasElement.querySelector<HTMLElement>(".nav-rail")!;
    await expect(getComputedStyle(rail).overflowY).not.toBe("auto");
    const toggle = canvas.getByRole("button", { name: "Collapse navigation" });
    await expect(scroll.getBoundingClientRect().top).toBeGreaterThanOrEqual(toggle.getBoundingClientRect().bottom);
  },
};

export const LongRailLight: Story = { ...LongRailScrollbarClearsToggle, globals: { theme: "light" } };
export const LongRailDark: Story = { ...LongRailScrollbarClearsToggle, globals: { theme: "dark" } };

export const LightTheme: Story = { ...LoggedInWithProjectRoute, globals: { theme: "light" } };
export const DarkTheme: Story = { ...LoggedInWithProjectRoute, globals: { theme: "dark" } };
