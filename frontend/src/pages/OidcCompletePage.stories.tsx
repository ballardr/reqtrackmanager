import type { Decorator, Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { expect, fn, waitFor, within } from "storybook/test";

import { withAuth } from "../testing/storybook-helpers";
import { OidcCompletePage } from "./OidcCompletePage";
import { clearReturnTo, rememberReturnTo } from "../utils/returnTo";
import { OIDC_CLIENT_NONCE_STORAGE_KEY } from "./OrgLoginPage";

const NONCE = "test-nonce-abc123";

/** Sets the URL (search and hash) with `history.replaceState`: assigning `window.location.search`
 * reloads the page and would abandon the test run, and one helper stops a story's `search` leaking into the next. */
function setLocation(searchAndHash: string) {
  window.history.replaceState(null, "", `${window.location.pathname}${searchAndHash}`);
}

const withOidcRoutes: Decorator = (Story) => (
  <MemoryRouter initialEntries={["/oidc-complete"]}>
    <Routes>
      <Route path="/oidc-complete" element={<Story />} />
      <Route path="/projects" element={<div>Projects landing page</div>} />
      <Route path="/projects/:projectId/requirements" element={<div>Requirements page</div>} />
      <Route path="/login" element={<div>Login page</div>} />
    </Routes>
  </MemoryRouter>
);

// Stable mock reference reconfigured per story in `beforeEach`; a fresh `fn()` in `decorators` is not
// reliably re-applied (see LoginPage.stories.tsx's `loginMock`).
const refreshUserMock = fn();

// The page reads `window.location.hash`/`search` (not router state) and `sessionStorage` once; each
// story sets both as OrgLoginPage.generateClientNonce and the backend redirect produce them.
const meta: Meta<typeof OidcCompletePage> = {
  title: "Pages/OidcCompletePage",
  component: OidcCompletePage,
  decorators: [withAuth(null, { refreshUser: refreshUserMock }), withOidcRoutes],
};
export default meta;

type Story = StoryObj<typeof OidcCompletePage>;

/** A matching nonce and a token in the fragment complete login and redirect to /projects; the page renders
 * nothing itself, so the assertion is on the resulting page. */
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

/** The page the person was on when sign-in was required is where single sign-on returns them. */
export const SuccessfulLoginReturnsToTheRememberedPage: Story = {
  beforeEach: () => {
    refreshUserMock.mockResolvedValue(undefined);
    sessionStorage.setItem(OIDC_CLIENT_NONCE_STORAGE_KEY, NONCE);
    rememberReturnTo("/projects/p1/requirements");
    setLocation(`#token=real-access-token&client_nonce=${NONCE}`);
    return clearReturnTo;
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Requirements page")).toBeInTheDocument());
  },
};

/** With no stored nonce (tab reopened mid-flow, page reached directly) there is nothing to compare, so the token is untrusted. */
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

/** A mismatched nonce (login CSRF) shows the generic error, so probing cannot tell "wrong nonce" from "no token". */
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

/** When the required OIDC group check (Organization.oidc_required_group) rejects the user no token is issued;
 * the nonce-checked query string carries a denial message instead. */
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
