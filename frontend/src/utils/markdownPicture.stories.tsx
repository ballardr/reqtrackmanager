import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import { attachmentFileId, MAX_CAPTION_CHARS, pictureMarkdown, PICTURE_START, unescapeLine } from "./markdownPicture";
import { parseMarkdown } from "./markdownIt";

/** How a picture of a record's own attachment is written and read. */
const meta: Meta = { title: "Utils/markdownPicture", render: () => <p>Pure helpers; see the interactions.</p> };
export default meta;

type Story = StoryObj;

const ID = "3f2c9a52-6c1e-4f6e-9b7a-0a1b2c3d4e5f";

export const APictureIsWrittenAndReadBackExactly: Story = {
  play: async () => {
    const source = pictureMarkdown(ID, "A [plot] \\ here", 'say "hi"');
    await expect(source).toBe(`![A \\[plot\\] \\\\ here](attachment:${ID} "say \\"hi\\"")`);
    const found = PICTURE_START.exec(source);
    await expect(found).not.toBeNull();
    await expect(unescapeLine(found?.[1] ?? "")).toBe("A [plot] \\ here");
    await expect(found?.[2]).toBe(ID);
    await expect(unescapeLine(found?.[3] ?? "")).toBe('say "hi"');
    // The product's reader reads the same words and caption from it.
    const image = parseMarkdown(source)[1].children?.[0];
    await expect(image?.type).toBe("image");
    await expect(image?.attrGet("title")).toBe('say "hi"');
  },
};

export const AnEmptyAlternativeTextAndCaptionAreLeftOut: Story = {
  play: async () => {
    await expect(pictureMarkdown(ID, "", "")).toBe(`![](attachment:${ID})`);
    await expect(pictureMarkdown(ID, "  two\nlines  ")).toBe(`![two lines](attachment:${ID})`);
  },
};

export const ACaptionIsCutAtTheLimit: Story = {
  play: async () => {
    const source = pictureMarkdown(ID, "x", "c".repeat(MAX_CAPTION_CHARS + 50));
    await expect(PICTURE_START.exec(source)?.[3]).toHaveLength(MAX_CAPTION_CHARS);
  },
};

export const OnlyTheCanonicalAttachmentAddressIsAPicture: Story = {
  play: async () => {
    await expect(attachmentFileId(`attachment:${ID}`)).toBe(ID);
    for (const bad of [`attachment:${ID.toUpperCase()}`, "attachment:nope", "https://example.com/a.png", `javascript:${ID}`, ""]) {
      await expect(attachmentFileId(bad)).toBeNull();
    }
  },
};
