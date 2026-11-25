import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import { appendTagParams } from "./tags";
import { appendReferenceParams, isWebUrl, referenceLabel, referencesText } from "./externalReferences";
import { draftFromReference, referenceInput, referenceInputs, referenceIsComplete, BLANK_REFERENCE } from "../components/referenceDraft";
import { buildReference } from "../testing/referencesFixtures";

/** The pure helpers behind external references: their text, the link rule, the list filter parameters and the draft conversion. */
const meta: Meta = { title: "Utils/externalReferences", render: () => <p>Pure helpers; see the interactions.</p> };
export default meta;

type Story = StoryObj;

export const WritesAReferenceAsText: Story = {
  play: async () => {
    await expect(referenceLabel(buildReference())).toBe("Jira: PROJ-1");
    await expect(referenceLabel(buildReference({ key: "", url: "https://x.example/1" }))).toBe("Jira: https://x.example/1");
    await expect(referencesText([buildReference(), buildReference({ key: "REQ-9" }, "s-doors")])).toBe("Jira: PROJ-1, DOORS: REQ-9");
    await expect(referencesText(undefined)).toBe("");
  },
};

/** Only an absolute http or https address is ever a link; script and data addresses are not, whatever the server stored. */
export const OnlyAWebAddressIsALink: Story = {
  play: async () => {
    await expect(isWebUrl("https://tracker.example/browse/PROJ-1")).toBe(true);
    await expect(isWebUrl("http://tracker.example")).toBe(true);
    for (const bad of ["javascript:alert(1)", "data:text/html,x", "ftp://x.example", "//x.example", "/relative", "PROJ-1", "", null, undefined]) {
      await expect(isWebUrl(bad)).toBe(false);
    }
  },
};

export const WritesTheFilterParameters: Story = {
  play: async () => {
    const params = new URLSearchParams();
    appendReferenceParams(params, { external_systems: ["Jira", "DOORS"], external_key: "  PROJ-1 " });
    await expect(params.toString()).toBe("external_system=Jira&external_system=DOORS&external_key=PROJ-1");
    const empty = new URLSearchParams();
    appendReferenceParams(empty, { external_systems: [], external_key: "   " });
    await expect(empty.toString()).toBe("");
  },
};

/** Every list API builds its read through the one writer. */
export const EveryListReadCarriesTheFilter: Story = {
  play: async () => {
    const read = new URLSearchParams();
    appendTagParams(read, { tags: ["Safety"], tag_mode: "all", external_systems: ["Jira"], external_key: "7" });
    await expect(read.toString()).toBe("external_system=Jira&external_key=7&tag=Safety&tag_mode=all");
  },
};

export const ConvertsADraftToTheApiBody: Story = {
  play: async () => {
    await expect(referenceIsComplete(BLANK_REFERENCE)).toBe(false);
    await expect(referenceIsComplete({ ...BLANK_REFERENCE, systemId: "s-jira" })).toBe(false);
    await expect(referenceIsComplete({ ...BLANK_REFERENCE, systemId: "s-jira", url: "https://x.example" })).toBe(true);
    await expect(referenceInput({ systemId: "s-jira", key: " PROJ-1 ", url: " ", note: " n ", role: "" })).toEqual({
      system_id: "s-jira", key: "PROJ-1", url: null, note: "n", role: null,
    });
    await expect(referenceInputs([{ ...BLANK_REFERENCE, systemId: "s-jira" }, { ...BLANK_REFERENCE, systemId: "s-doors", key: "REQ-1", role: "origin" }])).toEqual([
      { system_id: "s-doors", key: "REQ-1", url: null, note: "", role: "origin" },
    ]);
    await expect(draftFromReference(buildReference({ role: "delivery", note: "x", url: "https://x.example" }))).toEqual({
      systemId: "s-jira", key: "PROJ-1", url: "https://x.example", note: "x", role: "delivery",
    });
  },
};
