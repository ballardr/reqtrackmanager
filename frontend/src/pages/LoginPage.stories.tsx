import type { Decorator, Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../api/client";
import type { AnnouncementNotice, ServerSettings, SignupConfig } from "../api/types";
import { buildUser, withAuth, withRouter } from "../testing/storybook-helpers";
import { clearReturnTo, peekReturnTo, rememberReturnTo } from "../utils/returnTo";
import { LoginPage } from "./LoginPage";

const SERVER_SETTINGS: ServerSettings = {
  accent_color_hex: "#475569", default_logo_file_id: null, default_header_title: "ReqTrack Manager",
  logo_band_color_hex: null, logo_band_text_color_hex: null, footer_position: "after_content",
  default_login_background_file_id: null,
  email_footer_company_name: null, email_footer_website: null, email_footer_address: null,
  footer_prefix: null, company_id_label: null, company_id: null,
  org_label_singular: null, org_label_plural: null,
  file_uploads_enabled: true,
};

function mockBrandingAndSignup(
  signupMode: SignupConfig["signup_mode"] = "disabled", announcements: AnnouncementNotice[] = [], settings: ServerSettings = SERVER_SETTINGS,
) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.includes("/announcements/login")) return announcements;
    if (path.includes("signup-config")) return { signup_mode: signupMode, self_signup_organizations: [] } satisfies SignupConfig;
    return settings;
  });
}

// Stable mock references are reconfigured per story in `beforeEach` instead of a fresh `fn()` in
// `decorators`: Vitest browser mode does not fully remount LoginPage between stories, so a per-story
// closure could still return the previous story's resolved or rejected value.
const loginMock = fn();
const verify2faMock = fn();

const meta: Meta<typeof LoginPage> = {
  title: "Pages/LoginPage",
  component: LoginPage,
  // No router decorator at the meta level: story decorators compose with meta ones, and `ReauthMessage`
  // needs a MemoryRouter carrying route `state`; two nested routers are forbidden. Each other story adds
  // its own `withRouter("/login")`.
  decorators: [withAuth(null, { login: loginMock, verify2fa: verify2faMock })],
};
export default meta;

type Story = StoryObj<typeof LoginPage>;

export const Default: Story = {
  decorators: [withRouter("/login")],
  beforeEach: () => {
    mockBrandingAndSignup();
    loginMock.mockResolvedValue({ requires2fa: false, user: buildUser() });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // "Sign in" is both the heading and the submit button — scope to the heading.
    await expect(canvas.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    await expect(canvas.queryByText(/New here/)).not.toBeInTheDocument();
  },
};

/** The platform band colour is drawn behind the logo on the sign-in card; unset, it is the top bar colour. */
export const LogoBandColour: Story = {
  decorators: [withRouter("/login")],
  beforeEach: () => mockBrandingAndSignup("disabled", [], { ...SERVER_SETTINGS, logo_band_color_hex: "#0b5fa5" }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("heading", { name: "Sign in" });
    const band = canvasElement.querySelector<HTMLElement>(".logo-band");
    await expect(band?.style.background).toBe("rgb(11, 95, 165)");
  },
};

export const LogoBandDefault: Story = {
  decorators: [withRouter("/login")],
  beforeEach: () => mockBrandingAndSignup(),
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByRole("heading", { name: "Sign in" });
    await expect(canvasElement.querySelector<HTMLElement>(".logo-band")?.style.background).toContain("var(--color-header-bg)");
  },
};

/** Active platform messages flagged for login show above the form, as plain text. */
export const ShowsPlatformMessages: Story = {
  decorators: [withRouter("/login")],
  beforeEach: () => mockBrandingAndSignup("disabled", [
    { id: "n1", title: "Demo instance", body: "Sign in with the demo account.", severity: "information", scope: "server", dismissible: true },
  ]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("Demo instance")).toBeInTheDocument();
    await expect(canvas.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  },
};

/** Always offered, whatever the sign-up mode. */
export const OffersForgotPassword: Story = {
  decorators: [withRouter("/login")],
  beforeEach: () => mockBrandingAndSignup(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("link", { name: "Forgot your password?" })).toHaveAttribute("href", "/forgot-password");
  },
};

/** After a forced credential reset the correct password is refused with a 403 that points to the reset link. */
export const PasswordResetRequired: Story = {
  decorators: [withRouter("/login")],
  beforeEach: () => {
    mockBrandingAndSignup();
    loginMock.mockRejectedValue(
      new ApiError(403, 'Your password must be reset before you can sign in. Choose "Forgot your password?" to get a reset link.'),
    );
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByLabelText("Email"), "alex@example.com");
    await userEvent.type(canvas.getByLabelText("Password"), "old-password");
    await userEvent.click(canvas.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(canvas.getByText(/must be reset before you can sign in/)).toBeInTheDocument());
    await expect(canvas.getByRole("link", { name: "Forgot your password?" })).toBeInTheDocument();
  },
};

export const SignUpPromptShownWhenSignupEnabled: Story = {
  decorators: [withRouter("/login")],
  beforeEach: () => mockBrandingAndSignup("always_on"),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText(/New here/)).toBeInTheDocument());
  },
};

export const InvalidCredentials: Story = {
  decorators: [withRouter("/login")],
  beforeEach: () => {
    mockBrandingAndSignup();
    loginMock.mockRejectedValue(new ApiError(401, "Invalid email or password."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByLabelText("Email"), "alex@example.com");
    await userEvent.type(canvas.getByLabelText("Password"), "wrong-password");
    await userEvent.click(canvas.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(canvas.getByText("Invalid email or password.")).toBeInTheDocument());
  },
};

/** A 2FA-enrolled account's login returns a challenge token instead of a session; the page shows the code-entry form. */
export const TwoFactorChallenge: Story = {
  decorators: [withRouter("/login")],
  beforeEach: () => {
    mockBrandingAndSignup();
    loginMock.mockResolvedValue({ requires2fa: true, challengeToken: "challenge-1" });
    verify2faMock.mockResolvedValue(buildUser());
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByLabelText("Email"), "alex@example.com");
    await userEvent.type(canvas.getByLabelText("Password"), "correct-password");
    await userEvent.click(canvas.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(canvas.getByText("Two-factor verification")).toBeInTheDocument());
  },
};

const withReauthState: Decorator = (Story) => (
  <MemoryRouter initialEntries={[{ pathname: "/login", state: { message: "For your security, you have been signed out. Please sign in again." } }]}>
    <Story />
  </MemoryRouter>
);

/** Arrival after a forced logout (expired token, password changed elsewhere): App.tsx passes a `message` in router state. */
export const ReauthMessage: Story = {
  decorators: [withReauthState],
  beforeEach: () => mockBrandingAndSignup(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(/signed out/)).toBeInTheDocument();
  },
};

/** Login and the page it returns to, as two routes so a story can see where the person ends up. */
const withReturnRoutes: Decorator = (Story) => (
  <MemoryRouter initialEntries={["/login"]}>
    <Routes>
      <Route path="/login" element={<Story />} />
      <Route path="/projects/:projectId/requirements" element={<div>Requirements page</div>} />
      <Route path="/projects" element={<div>Landing page</div>} />
    </Routes>
  </MemoryRouter>
);

async function signIn(canvas: ReturnType<typeof within>) {
  await userEvent.type(canvas.getByLabelText("Email"), "alex@example.com");
  await userEvent.type(canvas.getByLabelText("Password"), "correct-password");
  await userEvent.click(canvas.getByRole("button", { name: "Sign in" }));
}

/** A page was remembered when sign-in was required: the form adds no text, and signing in returns to that page. */
export const ReturnsToTheRememberedPage: Story = {
  decorators: [withReturnRoutes],
  beforeEach: () => {
    mockBrandingAndSignup();
    clearReturnTo();
    rememberReturnTo("/projects/p1/requirements?status=open");
    loginMock.mockResolvedValue({ requires2fa: false, user: buildUser({ landing_preference: "overview" }) });
    return clearReturnTo;
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByText(/continue to the page you requested/)).not.toBeInTheDocument();
    await signIn(canvas);
    await waitFor(() => expect(canvas.getByText("Requirements page")).toBeInTheDocument());
    await expect(peekReturnTo()).toBeNull();
  },
};

/** Without a remembered page the landing preference applies. */
export const WithoutARememberedPageUsesTheLandingPreference: Story = {
  decorators: [withReturnRoutes],
  beforeEach: () => {
    mockBrandingAndSignup();
    clearReturnTo();
    loginMock.mockResolvedValue({ requires2fa: false, user: buildUser({ landing_preference: "overview" }) });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByText(/continue to the page you requested/)).not.toBeInTheDocument();
    await signIn(canvas);
    await waitFor(() => expect(canvas.getByText("Landing page")).toBeInTheDocument());
  },
};

/** A remembered path that is not on this site is ignored (open redirect). */
export const IgnoresAPathOnAnotherSite: Story = {
  decorators: [withReturnRoutes],
  beforeEach: () => {
    mockBrandingAndSignup();
    clearReturnTo();
    sessionStorage.setItem("reqtrack:return-to", "//evil.example/phish");
    loginMock.mockResolvedValue({ requires2fa: false, user: buildUser({ landing_preference: "overview" }) });
    return clearReturnTo;
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await signIn(canvas);
    await waitFor(() => expect(canvas.getByText("Landing page")).toBeInTheDocument());
  },
};

/** The two-factor step returns to the remembered page as well. */
export const TwoFactorReturnsToTheRememberedPage: Story = {
  decorators: [withReturnRoutes],
  beforeEach: () => {
    mockBrandingAndSignup();
    clearReturnTo();
    rememberReturnTo("/projects/p1/requirements");
    loginMock.mockResolvedValue({ requires2fa: true, challengeToken: "challenge-1" });
    verify2faMock.mockResolvedValue(buildUser({ landing_preference: "overview" }));
    return clearReturnTo;
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await signIn(canvas);
    await userEvent.type(await canvas.findByLabelText("Authentication code"), "123456");
    await userEvent.click(canvas.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(canvas.getByText("Requirements page")).toBeInTheDocument());
  },
};

export const LogoBandLightTheme: Story = { ...LogoBandDefault, globals: { theme: "light" } };
export const LogoBandDarkTheme: Story = { ...LogoBandDefault, globals: { theme: "dark" } };
export const LightTheme: Story = { ...Default, globals: { theme: "light" } };
export const DarkTheme: Story = { ...Default, globals: { theme: "dark" } };
