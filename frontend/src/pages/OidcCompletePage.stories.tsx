import type { Decorator, Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { expect, fn, waitFor, within } from "storybook/test";

import { withAuth } from "../testing/storybook-helpers";
import { OidcCompletePage } from "./OidcCompletePage";
import { OIDC_CLIENT_NONCE_STORAGE_KEY } from "./OrgLoginPage";

const NONCE = "test-nonce-abc123";

/** Sets the page's actual URL (path/search/hash) via `history.replaceState`
 * — never by assigning `window.location.search` directly, which triggers a
 * real page navigation/reload in a browser and would abandon the test run.
 * `window.location.hash`, unlike `.search`, is safe to assign directly (no
 * reload), but routing everything through one helper keeps every story's
 * URL setup consistent and avoids leaking a previous story's `search` into
 * the next one sharing this same browser page. */
function setLocation(searchAndHash: string) {
  window.history.replaceState(null, "", `${window.location.pathname}${searchAndHash}`);
}

const withOidcRoutes: Decorator = (Story) => (
  <MemoryRouter initialEntries={["/oidc-complete"]}>
    <Routes>
      <Route path="/oidc-complete" element={<Story />} />
      <Route path="/projects" element={<div>Projects landing page</div>} />
      <Route path="/login" element={<div>Login page</div>} />
    </Routes>
  </MemoryRouter>
);

// Stable mock reference, reconfigured per-story via `beforeEach` — see
// LoginPage.stories.tsx's `loginMock` comment for why a fresh `fn()`
// baked into a `decorators` array literal isn't reliably re-applied here.
const refreshUserMock = fn();

// Real behaviour is a one-shot side-effect sequence reading
// `window.location.hash`/`search` (not react-router state) plus
// `sessionStorage` — set both directly before each story, matching exactly
// what OrgLoginPage.generateClientNonce/the backend redirect produce.
const meta: Meta<typeof OidcCompletePage> = {
  title: "Pages/OidcCompletePage",
  component: OidcCompletePage,
  decorators: [withAuth(null, { refreshUser: refreshUserMock }), withOidcRoutes],
};
export default meta;

type Story = StoryObj<typeof OidcCompletePage>;

/** Matching nonce + a real token in the fragment — completes login and
 * redirects to /projects. Renders nothing itself (the success path is a
 * pure redirect), so the assertion is on the resulting page. */
export const SuccessfulLoginRedirects: Story = {
  beforeEach: () => {
    refreshUserMock.mockResolvedValue(undefined);
    sessionStorage.setItem(OIDC_CLIENT_NONCE_STORAGE_KEY, NONCE);
    setLocation(`#token=real-access-token&client_nonce=${NONCE}`);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Projects landing page")).toBeInTheDocument());
  },
};

/** No nonce ever stashed (e.g. the tab was closed/reopened mid-flow, or the
 * page was reached directly) — nothing to compare against, so it's treated
 * as untrusted. */
export const MissingNonceShowsError: Story = {
  beforeEach: () => {
    sessionStorage.removeItem(OIDC_CLIENT_NONCE_STORAGE_KEY);
    setLocation("#token=some-token&client_nonce=whatever");
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Invalid email or password.")).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "Sign in" })).toBeInTheDocument();
  },
};

/** A mismatched nonce is exactly the login-CSRF scenario this page exists
 * to block — same error, not a more specific "nonce mismatch" message, so
 * an attacker can't distinguish "wrong nonce" from "no token" by probing. */
export const MismatchedNonceShowsError: Story = {
  beforeEach: () => {
    sessionStorage.setItem(OIDC_CLIENT_NONCE_STORAGE_KEY, NONCE);
    setLocation("#token=some-token&client_nonce=a-different-nonce");
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Invalid email or password.")).toBeInTheDocument();
  },
};

/** The identity provider authenticated the user, but the org's required
 * OIDC group check rejected them (Organization.oidc_required_group) — no
 * token was ever issued server-side, so the (still nonce-checked) query
 * string carries a specific denial message instead. */
export const NotProvisionedShowsServerMessage: Story = {
  beforeEach: () => {
    sessionStorage.setItem(OIDC_CLIENT_NONCE_STORAGE_KEY, NONCE);
    setLocation(
      `?error=not_provisioned&message=${encodeURIComponent("Your organisation has not provisioned you access.")}&client_nonce=${NONCE}`
    );
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Your organisation has not provisioned you access.")).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...MissingNonceShowsError, globals: { theme: "light" } };
export const DarkTheme: Story = { ...MissingNonceShowsError, globals: { theme: "dark" } };
