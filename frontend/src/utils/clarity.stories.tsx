import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import { loadClarity, validClarityProjectId } from "./clarity";

/** Pure-function checks for the optional Clarity loader, run as stories like the other helpers. */
const meta: Meta = { title: "Utils/Clarity" };
export default meta;

type Story = StoryObj;

export const OnlyAWellFormedIdentifierIsAccepted: Story = {
  render: () => <div>Identifier check</div>,
  play: async () => {
    await expect(validClarityProjectId("abc123xyz9")).toBe("abc123xyz9");
    await expect(validClarityProjectId("  abc123xyz9 ")).toBe("abc123xyz9");
    for (const bad of [undefined, null, "", "ab", 'x";alert(1);//', "a/b/c/d", "abc def ghi"]) {
      await expect(validClarityProjectId(bad)).toBeNull();
    }
  },
};

export const NothingLoadsWithoutAnIdentifier: Story = {
  render: () => <div>Disabled</div>,
  play: async () => {
    const doc = document.implementation.createHTMLDocument("clarity");
    await expect(loadClarity(undefined, doc)).toBe(false);
    await expect(loadClarity("not valid!", doc)).toBe(false);
    await expect(doc.querySelectorAll("script").length).toBe(0);
  },
};

export const TheScriptIsAddedOnceFromTheClarityHost: Story = {
  render: () => <div>Enabled</div>,
  play: async () => {
    const doc = document.implementation.createHTMLDocument("clarity");
    await expect(loadClarity("abc123xyz9", doc)).toBe(true);
    await expect(loadClarity("abc123xyz9", doc)).toBe(false);
    const scripts = doc.querySelectorAll("script");
    await expect(scripts.length).toBe(1);
    await expect(scripts[0].src).toBe("https://www.clarity.ms/tag/abc123xyz9");
  },
};
