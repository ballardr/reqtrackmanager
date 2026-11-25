import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import { parsePoliciesPath } from "./policiesPath";

/** The reader of the Policies page's addresses: a policy, a licence section, or nothing named. */
const meta: Meta = { title: "Utils/policiesPath", render: () => <p>Pure helper; see the interactions.</p> };
export default meta;

type Story = StoryObj;

export const NamesAPolicyOrNone: Story = {
  play: async () => {
    await expect(parsePoliciesPath("/policies")).toEqual({ kind: "policy", id: null });
    await expect(parsePoliciesPath("/policies/")).toEqual({ kind: "policy", id: null });
    await expect(parsePoliciesPath("/policies/abc-123")).toEqual({ kind: "policy", id: "abc-123" });
    await expect(parsePoliciesPath("/policies/a%20b")).toEqual({ kind: "policy", id: "a b" });
  },
};

export const NamesALicenceSection: Story = {
  play: async () => {
    await expect(parsePoliciesPath("/policies/licences/fonts")).toEqual({ kind: "licences", section: "fonts" });
    await expect(parsePoliciesPath("/policies/licences/components/extra")).toEqual({ kind: "licences", section: "components" });
  },
};

export const AnUnknownSectionIsTheFirst: Story = {
  play: async () => {
    await expect(parsePoliciesPath("/policies/licences")).toEqual({ kind: "licences", section: "product" });
    await expect(parsePoliciesPath("/policies/licences/nothing")).toEqual({ kind: "licences", section: "product" });
  },
};

export const AMalformedEscapeNamesNoPolicy: Story = {
  play: async () => {
    await expect(parsePoliciesPath("/policies/%E0%A4%A")).toEqual({ kind: "policy", id: null });
  },
};
