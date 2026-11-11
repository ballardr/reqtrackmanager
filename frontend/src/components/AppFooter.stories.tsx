import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { ServerSettings } from "../api/types";
import { buildMemberPolicy, buildPublicPolicy, buildUser, withAuth, withRouter } from "../testing/storybook-helpers";
import { AppFooter } from "./AppFooter";

/** The footer every page ends with: server company details, the policies link and the versions, separated by `|` between two groups on one line. */
const meta: Meta<typeof AppFooter> = { title: "Components/AppFooter", component: AppFooter, decorators: [withRouter("/")] };
export default meta;

type Story = StoryObj<typeof AppFooter>;

const SETTINGS: ServerSettings = {
  accent_color_hex: "#475569", default_logo_file_id: null, default_header_title: null, default_login_background_file_id: null,
  logo_band_color_hex: null, logo_band_text_color_hex: null, footer_position: "after_content",
  email_footer_company_name: null, email_footer_website: null, email_footer_address: null,
  footer_prefix: null, company_id_label: null, company_id: null,
  org_label_singular: null, org_label_plural: null, file_uploads_enabled: true,
};

/** Routes the footer's reads by path. */
function mockReads(settings: Partial<ServerSettings>, policies: unknown[], memberPolicies: unknown[] = []) {
  spyOn(api, "get").mockImplementation(async (path: string): Promise<unknown> => {
    if (path === "/api/v1/system/branding") return { ...SETTINGS, ...settings };
    if (path === "/api/v1/public/policies") return policies;
    if (path === "/api/v1/policies/mine") return memberPolicies;
    if (path === "/api/v1/system/version") return { version: "1.4.0", git_sha: "abc1234", build_date: "2026-08-15T09:00:00Z" };
    throw new Error(`unmocked path in AppFooter story: ${path}`);
  });
}

/** The text of each group, in order: the separators are drawn by the stylesheet, so they are not part of any text. */
function groupTexts(footer: HTMLElement): string[] {
  return Array.from(footer.querySelectorAll(".app-footer-group"), (group) => group.textContent ?? "");
}

/** Whether a group draws a separator before it, read from the stylesheet's generated content. */
function drawsSeparator(group: Element): boolean {
  return getComputedStyle(group, "::before").content.includes("|");
}

/** Signed out: the application version only (the API version needs a session), no company details when unset. */
export const SignedOutWithNothingElse: Story = {
  beforeEach: () => {
    mockReads({}, []);
  },
  play: async ({ canvasElement }) => {
    const footer = within(canvasElement).getByRole("contentinfo", { name: "Page footer" });
    await expect(within(footer).getByText("Version: vdev")).toBeInTheDocument();
    await waitFor(() => expect(api.get).toHaveBeenCalledWith("/api/v1/system/branding"));
    await expect(within(footer).queryByRole("link")).not.toBeInTheDocument();
    await expect(within(footer).queryByText(/\/v/)).not.toBeInTheDocument();
  },
};

/** Prefix and name (linking to the website, which gets https:// when it has no scheme), address, company identifier, policies, versions, with `|` between. */
export const SignedInWithEverything: Story = {
  decorators: [withAuth(buildUser())],
  beforeEach: () => {
    mockReads(
      { email_footer_company_name: "Acme Pty Ltd", email_footer_website: "www.acme.example.com", email_footer_address: "1 Main Street\nSydney NSW 2000",
        footer_prefix: "Hosted by", company_id_label: "ABN", company_id: "12 345 678 901" },
      [buildPublicPolicy()],
    );
  },
  play: async ({ canvasElement }) => {
    const footer = within(canvasElement).getByRole("contentinfo", { name: "Page footer" });
    const company = await within(footer).findByRole("link", { name: "Acme Pty Ltd" });
    await expect(company).toHaveAttribute("href", "https://www.acme.example.com");
    await expect(within(footer).getByText("1 Main Street, Sydney NSW 2000")).toBeInTheDocument();
    await expect(within(footer).getByRole("link", { name: "Policies" })).toHaveAttribute("href", "/policies");
    await expect(await within(footer).findByText("Version: vdev/v1.4.0")).toBeInTheDocument();
    // Five groups; the policies sit between the company identifier and the versions.
    await expect(groupTexts(footer)).toEqual(["Hosted by Acme Pty Ltd", "1 Main Street, Sydney NSW 2000", "ABN 12 345 678 901", "Policies", "Version: vdev/v1.4.0"]);
    // Wide enough for one line: a separator before every group but the first.
    await waitFor(() => {
      const groups = Array.from(footer.querySelectorAll(".app-footer-group"));
      expect(groups.map(drawsSeparator)).toEqual([false, true, true, true, true]);
    });
  },
};

/** A group that is absent leaves no separator: only the address and versions here. */
export const AddressOnlyHasNoStraySeparators: Story = {
  beforeEach: () => {
    mockReads({ email_footer_address: "1 Main Street" }, []);
  },
  play: async ({ canvasElement }) => {
    const footer = within(canvasElement).getByRole("contentinfo", { name: "Page footer" });
    await waitFor(() => expect(groupTexts(footer)).toEqual(["1 Main Street", "Version: vdev"]));
  },
};

/** An organisation policy alone is enough for the link. */
export const OrganisationPolicyShowsTheLink: Story = {
  decorators: [withAuth(buildUser())],
  beforeEach: () => {
    mockReads({}, [], [buildMemberPolicy()]);
  },
  play: async ({ canvasElement }) => {
    const footer = within(canvasElement).getByRole("contentinfo", { name: "Page footer" });
    await expect(await within(footer).findByRole("link", { name: "Policies" })).toHaveAttribute("href", "/policies");
  },
};

/** A website with another scheme is shown as text and never becomes a link. */
export const UnsafeWebsiteIsNotALink: Story = {
  beforeEach: () => {
    mockReads({ email_footer_website: "javascript:alert(1)" }, []);
  },
  play: async ({ canvasElement }) => {
    const footer = within(canvasElement).getByRole("contentinfo", { name: "Page footer" });
    await expect(await within(footer).findByText("javascript:alert(1)")).toBeInTheDocument();
    await expect(within(footer).queryByRole("link")).not.toBeInTheDocument();
  },
};

/** The prefix needs a company name, and an identifier with no label is shown on its own. */
export const PrefixNeedsANameAndTheIdentifierNeedsNoLabel: Story = {
  beforeEach: () => {
    mockReads({ footer_prefix: "Hosted by", company_id: "99 888" }, []);
  },
  play: async ({ canvasElement }) => {
    const footer = within(canvasElement).getByRole("contentinfo", { name: "Page footer" });
    await waitFor(() => expect(groupTexts(footer)).toEqual(["99 888", "Version: vdev"]));
  },
};

/** Every group present at one width. */
const EVERYTHING = {
  email_footer_company_name: "Acme Pty Ltd", email_footer_website: "www.acme.example.com",
  email_footer_address: "Level 12, 100 Collins Street\nMelbourne VIC 3000", footer_prefix: "Hosted by",
  company_id_label: "ABN", company_id: "12 345 678 901",
};

/**
 * Asserts, by measured geometry, that no line of the footer begins or ends on a separator: a group draws one only when
 * the group before it is on the same line, and the last group of a line is never followed by one.
 */
async function expectNoDanglingSeparators(footer: HTMLElement) {
  await waitFor(() => {
    const groups = Array.from(footer.querySelectorAll<HTMLElement>(".app-footer-group"));
    expect(groups.length).toBe(5);
    groups.forEach((group, index) => {
      const sharesLine = index > 0 && group.offsetTop === groups[index - 1].offsetTop;
      // A separator before a group is present exactly when its neighbour on the left is on the same line, so a line
      // never starts with one (its first group has no left neighbour on the line) and never ends with one (a
      // separator belongs to the group after it, never the group before it).
      expect(drawsSeparator(group)).toBe(sharesLine);
    });
  });
}

/** A narrow column wraps the footer onto several lines; no line ends on, or begins with, a separator. */
export const NarrowWidthNeverLeavesASeparatorAtALineEdge: Story = {
  decorators: [(Story) => <div style={{ width: 280 }}><Story /></div>],
  beforeEach: () => {
    mockReads(EVERYTHING, [buildPublicPolicy()]);
  },
  play: async ({ canvasElement }) => {
    const footer = within(canvasElement).getByRole("contentinfo", { name: "Page footer" });
    await within(footer).findByText("Version: vdev");
    await expectNoDanglingSeparators(footer);
    // At this width the groups really do wrap (otherwise the check proves nothing).
    const tops = new Set(Array.from(footer.querySelectorAll<HTMLElement>(".app-footer-group"), (group) => group.offsetTop));
    await expect(tops.size).toBeGreaterThan(1);
  },
};

/** Several widths between narrow and wide: the rule holds at each, including when the width changes after the first paint. */
export const EveryWidthKeepsTheRule: Story = {
  render: () => <div id="footer-box" style={{ width: 900 }}><AppFooter /></div>,
  beforeEach: () => {
    mockReads(EVERYTHING, [buildPublicPolicy()]);
  },
  play: async ({ canvasElement }) => {
    const footer = within(canvasElement).getByRole("contentinfo", { name: "Page footer" });
    const box = canvasElement.querySelector<HTMLElement>("#footer-box")!;
    await within(footer).findByText("Version: vdev");
    for (const width of [900, 640, 460, 340, 260, 220, 700]) {
      box.style.width = `${width}px`;
      await expectNoDanglingSeparators(footer);
    }
  },
};
