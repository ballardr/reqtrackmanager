import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { ServerSettings } from "../api/types";
import { withRouter } from "../testing/storybook-helpers";
import { SignedOutPage } from "./SignedOutPage";

/** The shell of the signed-out pages: a narrow column of cards with the footer below them or at the foot of the window. */
const meta: Meta<typeof SignedOutPage> = { title: "Components/SignedOutPage", component: SignedOutPage, decorators: [withRouter("/")] };
export default meta;

type Story = StoryObj<typeof SignedOutPage>;

const SETTINGS: ServerSettings = {
  accent_color_hex: "#475569", default_logo_file_id: null, default_header_title: null, default_login_background_file_id: null,
  logo_band_color_hex: null, logo_band_text_color_hex: null, footer_position: "after_content",
  email_footer_company_name: "Acme Pty Ltd", email_footer_website: null, email_footer_address: null,
  footer_prefix: null, company_id_label: null, company_id: null,
  org_label_singular: null, org_label_plural: null, file_uploads_enabled: true,
};

/** Answers the platform branding read with `settings`; every other read is empty. */
function mockPlatform(settings: Partial<ServerSettings>) {
  spyOn(api, "get").mockImplementation(async (path: string): Promise<unknown> => {
    if (path === "/api/v1/system/branding") return { ...SETTINGS, ...settings };
    if (path === "/api/v1/system/version") return { version: "1.4.0", git_sha: "abc1234", build_date: "2026-08-15T09:00:00Z" };
    return [];
  });
}

const card = <div className="card">A sign-in card</div>;

/** The page shell, which is at least as tall as the window. */
function pageShell(canvasElement: HTMLElement): HTMLElement {
  return canvasElement.querySelector<HTMLElement>(".signed-out-page")!;
}

/** The vertical gap between the card's bottom edge and the footer's top edge, in pixels. */
function gapBelowCard(canvasElement: HTMLElement): number {
  const cardBox = within(canvasElement).getByText("A sign-in card").getBoundingClientRect();
  return canvasElement.querySelector("footer")!.getBoundingClientRect().top - cardBox.bottom;
}

/** The platform setting is the default: the footer follows the card, with the window's remaining height below it. */
export const AfterTheContent: Story = {
  args: { children: card },
  beforeEach: () => mockPlatform({ footer_position: "after_content" }),
  play: async ({ canvasElement }) => {
    const footer = await within(canvasElement).findByRole("contentinfo", { name: "Page footer" });
    await within(footer).findByText("Acme Pty Ltd");
    await expect(gapBelowCard(canvasElement)).toBeLessThan(80);
    await expect(footer.getBoundingClientRect().bottom).toBeLessThan(pageShell(canvasElement).getBoundingClientRect().bottom - 100);
  },
};

/** The platform setting puts the footer's bottom edge at the bottom edge of the page, which is at least the window's height. */
export const BottomOfThePage: Story = {
  args: { children: card },
  beforeEach: () => mockPlatform({ footer_position: "bottom_of_page" }),
  play: async ({ canvasElement }) => {
    const footer = await within(canvasElement).findByRole("contentinfo", { name: "Page footer" });
    await within(footer).findByText("Acme Pty Ltd");
    await waitFor(() => expect(Math.abs(footer.getBoundingClientRect().bottom - pageShell(canvasElement).getBoundingClientRect().bottom)).toBeLessThanOrEqual(1));
    await expect(pageShell(canvasElement).getBoundingClientRect().height).toBeGreaterThanOrEqual(window.innerHeight);
    await expect(gapBelowCard(canvasElement)).toBeGreaterThan(80);
  },
};

/** A position passed by the caller (an organisation's own sign-in page) wins over the platform setting. */
export const CallerPositionOverridesThePlatform: Story = {
  args: { children: card, footerPosition: "bottom_of_page" },
  beforeEach: () => mockPlatform({ footer_position: "after_content" }),
  play: async ({ canvasElement }) => {
    const footer = await within(canvasElement).findByRole("contentinfo", { name: "Page footer" });
    await waitFor(() => expect(Math.abs(footer.getBoundingClientRect().bottom - pageShell(canvasElement).getBoundingClientRect().bottom)).toBeLessThanOrEqual(1));
  },
};

/** The footer sits after the cards when they are taller than the window; the page scrolls, nothing overlaps. */
export const TallContentKeepsTheFooterAfterIt: Story = {
  args: { children: <div className="card" style={{ height: 1400 }}>A sign-in card</div>, footerPosition: "bottom_of_page" },
  beforeEach: () => mockPlatform({}),
  play: async ({ canvasElement }) => {
    const footer = await within(canvasElement).findByRole("contentinfo", { name: "Page footer" });
    const cardBox = within(canvasElement).getByText("A sign-in card").getBoundingClientRect();
    await expect(footer.getBoundingClientRect().top).toBeGreaterThanOrEqual(cardBox.bottom);
  },
};
