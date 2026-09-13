import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import { buildUser, withAuth, withToast } from "../testing/storybook-helpers";
import { ModuleFrame } from "./ModuleFrame";

// A genuinely cross-origin frameUrl would make the browser navigate the
// rendered <iframe> there for real mid-test, tainting `contentWindow` into
// an inaccessible cross-origin proxy that a later `spyOn`/`mockRestore`
// can't redefine `postMessage` on (a real `SecurityError`, not a test bug)
// — same-origin keeps `contentWindow` genuinely accessible for the whole
// test, while every assertion below only cares about the `origin` *string*
// on each message, which is exercised identically either way.
const FRAME_ORIGIN = window.location.origin;
const FRAME_URL = `${FRAME_ORIGIN}/module-frame-test-fixture`;

/**
 * Storybook coverage for the Tier B Host UI Bridge (compliance-module-
 * plan.md Phase 3): no real remote module exists yet to point this at (the
 * plan's own Phase 3 spec builds the mechanism only — see docs/compliance-
 * module-plan.md), so every story here drives the bridge directly —
 * dispatching a synthetic `MessageEvent` with `source` set to the rendered
 * iframe's own `contentWindow` and `origin` set to `FRAME_ORIGIN` — exactly
 * the shape a real cross-origin module's own script would send.
 */
const meta: Meta<typeof ModuleFrame> = {
  title: "Components/ModuleFrame",
  component: ModuleFrame,
  decorators: [withAuth(buildUser({ display_name: "Alex Morgan" })), withToast()],
  args: {
    moduleKey: "fake_module",
    frameUrl: FRAME_URL,
    navLabel: "Fake Module",
    projectId: "project-1",
  },
  beforeEach: () => {
    spyOn(api, "post").mockResolvedValue({ token: "fake.module.frame.token", expires_in_minutes: 15 });
  },
};
export default meta;

type Story = StoryObj<typeof ModuleFrame>;

function getIframe(canvasElement: HTMLElement): HTMLIFrameElement {
  const iframe = canvasElement.querySelector("iframe");
  if (!iframe) throw new Error("ModuleFrame did not render an iframe");
  return iframe;
}

/** Mints a project-scoped frame token on mount, then — once the iframe
 * fires `load` — sends the `init` message carrying that token (never the
 * viewer's real session token) to the iframe's own origin, not `"*"`. */
export const MintsTokenAndSendsInitOnLoad: Story = {
  play: async ({ canvasElement }) => {
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/api/v1/projects/project-1/modules/fake_module/frame-token")
    );
    const iframe = getIframe(canvasElement);
    const postMessageSpy = spyOn(iframe.contentWindow!, "postMessage");
    iframe.dispatchEvent(new Event("load"));

    await waitFor(() => expect(postMessageSpy).toHaveBeenCalled());
    const [message, targetOrigin] = postMessageSpy.mock.calls[0] as [
      { type: string; context: Record<string, unknown> }, string,
    ];
    await expect(message.type).toBe("init");
    await expect(targetOrigin).toBe(FRAME_ORIGIN);
    await expect(message.context.token).toBe("fake.module.frame.token");
    await expect(message.context.projectId).toBe("project-1");
    await expect(message.context.organizationId).toBe(null);
    await expect((message.context.user as { displayName: string }).displayName).toBe("Alex Morgan");
  },
};

/** `{type: "toast", ...}` from the module is relayed onto the host's real
 * `useToast()` — the same `Toast` component every other page's mutations
 * use, not a lookalike rendered inside the iframe's own isolated DOM. */
export const RelaysToastFromModule: Story = {
  play: async ({ canvasElement }) => {
    const iframe = getIframe(canvasElement);
    window.dispatchEvent(
      new MessageEvent("message", {
        data: { type: "toast", message: "Standard published", variant: "success" },
        origin: FRAME_ORIGIN,
        source: iframe.contentWindow,
      })
    );
    const body = within(document.body);
    await waitFor(() => expect(body.getByText("Standard published")).toBeInTheDocument());
  },
};

/** A message from an origin other than the iframe's own declared
 * `frameUrl` origin must be ignored outright — otherwise any page embedded
 * anywhere could forge toasts/confirms into this host. */
export const IgnoresMessagesFromAnUntrustedOrigin: Story = {
  play: async ({ canvasElement }) => {
    const iframe = getIframe(canvasElement);
    window.dispatchEvent(
      new MessageEvent("message", {
        data: { type: "toast", message: "Should never appear", variant: "success" },
        origin: "https://not-the-allowlisted-origin.example.com",
        source: iframe.contentWindow,
      })
    );
    await new Promise((resolve) => setTimeout(resolve, 50));
    const body = within(document.body);
    await expect(body.queryByText("Should never appear")).not.toBeInTheDocument();
  },
};

/** `{type: "confirm", requireTypedText}` renders the host's real Tier 2
 * `ConfirmDialog` (typed-confirmation required before Confirm enables);
 * confirming replies `{type: "confirm_result", confirmed: true}` back to
 * the iframe's own origin, echoing the same `id` the module sent. */
export const ConfirmRoundTripTierTwo: Story = {
  play: async ({ canvasElement }) => {
    const iframe = getIframe(canvasElement);
    const postMessageSpy = spyOn(iframe.contentWindow!, "postMessage");
    window.dispatchEvent(
      new MessageEvent("message", {
        data: {
          type: "confirm", id: "req-42", title: "Delete standard?",
          message: "This cannot be undone.", requireTypedText: "ISO 27001",
        },
        origin: FRAME_ORIGIN,
        source: iframe.contentWindow,
      })
    );

    const body = within(document.body);
    await waitFor(() => expect(body.getByRole("heading", { name: "Delete standard?" })).toBeInTheDocument());
    const confirmButton = body.getByRole("button", { name: "Confirm" });
    await expect(confirmButton).toBeDisabled();

    await userEvent.type(body.getByRole("textbox"), "ISO 27001");
    await expect(confirmButton).toBeEnabled();
    await userEvent.click(confirmButton);

    await waitFor(() =>
      expect(postMessageSpy).toHaveBeenCalledWith({ type: "confirm_result", id: "req-42", confirmed: true }, FRAME_ORIGIN)
    );
    await expect(body.queryByRole("heading", { name: "Delete standard?" })).not.toBeInTheDocument();
  },
};

/** Cancelling the relayed `ConfirmDialog` replies `confirmed: false`. */
export const ConfirmRoundTripCancel: Story = {
  play: async ({ canvasElement }) => {
    const iframe = getIframe(canvasElement);
    const postMessageSpy = spyOn(iframe.contentWindow!, "postMessage");
    window.dispatchEvent(
      new MessageEvent("message", {
        data: { type: "confirm", id: "req-7", title: "Archive requirement mapping?", message: "You can restore it later." },
        origin: FRAME_ORIGIN,
        source: iframe.contentWindow,
      })
    );

    const body = within(document.body);
    await waitFor(() => expect(body.getByRole("heading", { name: "Archive requirement mapping?" })).toBeInTheDocument());
    await userEvent.click(body.getByRole("button", { name: "Cancel" }));

    await waitFor(() =>
      expect(postMessageSpy).toHaveBeenCalledWith({ type: "confirm_result", id: "req-7", confirmed: false }, FRAME_ORIGIN)
    );
  },
};
