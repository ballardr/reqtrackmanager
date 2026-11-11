import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { renderMarkdown } from "./safeMarkdown";

/** The text widget's markdown subset: what it renders, and what it refuses to. */
const meta: Meta = { title: "Utils/SafeMarkdown" };
export default meta;

type Story = StoryObj;

const show = (text: string) => <div data-testid="out">{renderMarkdown(text)}</div>;

export const Blocks: Story = {
  render: () => show("# Title\n\nFirst line\nsecond line\n\n- one\n- two\n\n1. first\n2. second\n\n> quoted\n\n---"),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("heading", { level: 3, name: "Title" })).toBeInTheDocument();
    await expect(canvas.getAllByRole("list")).toHaveLength(2);
    await expect(canvas.getAllByRole("listitem")).toHaveLength(4);
    await expect(canvasElement.querySelector("blockquote")).toHaveTextContent("quoted");
    await expect(canvasElement.querySelector("hr")).not.toBeNull();
    // A line break inside a paragraph is kept.
    await expect(canvasElement.querySelector("p br")).not.toBeNull();
  },
};

export const InlineMarks: Story = {
  render: () => show("Some **bold**, *italic*, _also italic_ and `code`."),
  play: async ({ canvasElement }) => {
    await expect(canvasElement.querySelector("strong")).toHaveTextContent("bold");
    await expect(canvasElement.querySelectorAll("em")).toHaveLength(2);
    await expect(canvasElement.querySelector("code")).toHaveTextContent("code");
  },
};

export const OnlyWebLinksAreLinks: Story = {
  render: () => show("[ok](https://example.com/a) and [bad](javascript:alert(1)) and [local](/projects)"),
  play: async ({ canvasElement }) => {
    const links = canvasElement.querySelectorAll("a");
    await expect(links).toHaveLength(1);
    await expect(links[0]).toHaveAttribute("href", "https://example.com/a");
    await expect(links[0]).toHaveAttribute("target", "_blank");
    await expect(links[0]).toHaveAttribute("rel", "noopener noreferrer");
    // The refused ones stay on the page as the text typed.
    await expect(canvasElement).toHaveTextContent("[bad](javascript:alert(1))");
  },
};

export const HtmlAndImagesAreText: Story = {
  render: () => show('<img src=x onerror="alert(1)"> <script>alert(1)</script> ![pic](https://example.com/p.png)'),
  play: async ({ canvasElement }) => {
    await expect(canvasElement.querySelector("img")).toBeNull();
    await expect(canvasElement.querySelector("script")).toBeNull();
    await expect(canvasElement).toHaveTextContent("<script>alert(1)</script>");
  },
};

export const BlankTextRendersNothing: Story = {
  render: () => show("  \n\n "),
  play: async ({ canvasElement }) => {
    await expect(canvasElement.querySelector('[data-testid="out"]')).toBeEmptyDOMElement();
  },
};
