import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import type { PolicyBody } from "../api/types";
import { PolicyBodyView } from "./PolicyBodyView";

const FULL: PolicyBody = {
  type: "doc",
  content: [
    { type: "heading", attrs: { level: 1 }, content: [{ type: "text", text: "Scope" }] },
    { type: "paragraph", content: [
      { type: "text", text: "Read ", marks: [{ type: "bold" }] },
      { type: "text", text: "this", marks: [{ type: "italic" }] },
      { type: "text", text: " page", marks: [{ type: "link", attrs: { href: "https://example.org/p" } }] },
    ] },
    { type: "bulletList", content: [{ type: "listItem", content: [{ type: "paragraph", content: [{ type: "text", text: "One" }] }] }] },
    { type: "orderedList", attrs: { start: 3 }, content: [{ type: "listItem", content: [{ type: "paragraph", content: [{ type: "text", text: "Three" }] }] }] },
    { type: "blockquote", content: [{ type: "paragraph", content: [{ type: "text", text: "Quoted" }] }] },
    { type: "horizontalRule" },
  ],
};

/** A policy body rendered from the server's limited rich-text document. */
const meta: Meta<typeof PolicyBodyView> = { title: "Components/PolicyBodyView", component: PolicyBodyView };
export default meta;

type Story = StoryObj<typeof PolicyBodyView>;

/** Every allowed block and style renders; a link opens in a new tab without exposing the opener. */
export const RendersEveryAllowedNode: Story = {
  args: { body: FULL },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("heading", { name: "Scope" })).toBeInTheDocument();
    await expect(canvas.getByText("Read")).toContainHTML("strong");
    const link = canvas.getByRole("link", { name: "page" });
    await expect(link).toHaveAttribute("rel", "noopener noreferrer");
    await expect(link).toHaveAttribute("target", "_blank");
    await expect(canvas.getAllByRole("list")).toHaveLength(2);
    await expect(canvasElement.querySelector("ol")).toHaveAttribute("start", "3");
    await expect(canvasElement.querySelector("blockquote")).not.toBeNull();
    await expect(canvasElement.querySelector("hr")).not.toBeNull();
  },
};

/** Markup in the text is shown as text, and an address that is not https, http or mailto is not a link. */
export const NeverInsertsMarkupOrUnsafeLinks: Story = {
  args: {
    body: { type: "doc", content: [{ type: "paragraph", content: [
      { type: "text", text: "<img src=x onerror=alert(1)>" },
      { type: "text", text: "bad link", marks: [{ type: "link", attrs: { href: "javascript:alert(1)" } }] },
    ] }] },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
    await expect(canvasElement.querySelector("img")).toBeNull();
    await expect(canvas.queryByRole("link")).not.toBeInTheDocument();
    await expect(canvas.getByText("bad link")).toBeInTheDocument();
  },
};
