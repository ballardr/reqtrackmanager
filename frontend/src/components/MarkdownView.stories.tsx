import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, waitFor, within } from "storybook/test";

import { MarkdownView } from "./MarkdownView";

/** Markdown text as read-only content: what it formats, what it refuses, and how a diagram is drawn. */
const meta: Meta<typeof MarkdownView> = { title: "Components/MarkdownView", component: MarkdownView };
export default meta;

type Story = StoryObj<typeof MarkdownView>;

const FLOW = "```mermaid\nflowchart LR\n  A[Request] --> B{Approved?}\n  B -->|Yes| C[Build]\n  B -->|No| D[Revise]\n```";

export const Blocks: Story = {
  args: { text: "# Title\n\nFirst line\nsecond line\n\n- one\n- two\n\n1. first\n2. second\n\n> quoted\n\n---\n\n```\nlet x = 1;\n```" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // The page owns the first two heading levels, so # is the third.
    await expect(canvas.getByRole("heading", { level: 3, name: "Title" })).toBeInTheDocument();
    await expect(canvas.getAllByRole("list")).toHaveLength(2);
    await expect(canvas.getAllByRole("listitem")).toHaveLength(4);
    await expect(canvasElement.querySelector("blockquote")).toHaveTextContent("quoted");
    await expect(canvasElement.querySelector("hr")).not.toBeNull();
    await expect(canvasElement.querySelector("pre code")).toHaveTextContent("let x = 1;");
    // A single line break inside a paragraph is kept.
    await expect(canvasElement.querySelector("p br")).not.toBeNull();
  },
};

export const InlineMarks: Story = {
  args: { text: "Some **bold**, *italic*, _also italic_, ~~struck~~ and `code`." },
  play: async ({ canvasElement }) => {
    await expect(canvasElement.querySelector("strong")).toHaveTextContent("bold");
    await expect(canvasElement.querySelectorAll("em")).toHaveLength(2);
    await expect(canvasElement.querySelector("s")).toHaveTextContent("struck");
    await expect(canvasElement.querySelector("code")).toHaveTextContent("code");
  },
};

export const Tables: Story = {
  args: { text: "| Option | Cost |\n| :-- | --: |\n| Build | 10 |\n| Buy | 4 |" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual(["Option", "Cost"]);
    await expect(canvas.getAllByRole("row")).toHaveLength(3);
    await expect(canvas.getByRole("cell", { name: "10" })).toHaveStyle({ textAlign: "right" });
  },
};

export const OnlyWebAndMailLinksAreLinks: Story = {
  args: { text: "[ok](https://example.com/a) and [mail](mailto:a@example.com) and [bad](javascript:alert(1)) and [local](/projects) and [data](data:text/html,x)" },
  play: async ({ canvasElement }) => {
    const links = canvasElement.querySelectorAll("a");
    await expect(links).toHaveLength(2);
    await expect(links[0]).toHaveAttribute("href", "https://example.com/a");
    await expect(links[0]).toHaveAttribute("target", "_blank");
    await expect(links[0]).toHaveAttribute("rel", "noopener noreferrer");
    await expect(links[1]).toHaveAttribute("href", "mailto:a@example.com");
    // The refused ones stay on the page as the text typed.
    await expect(canvasElement).toHaveTextContent("[bad](javascript:alert(1))");
  },
};

export const HtmlAndImagesAreText: Story = {
  args: { text: '<img src=x onerror="alert(1)"> <script>alert(1)</script> <b onclick="x()">b</b>\n\n![pic](https://example.com/p.png)\n\n<div>block</div>' },
  play: async ({ canvasElement }) => {
    await expect(canvasElement.querySelector("img")).toBeNull();
    await expect(canvasElement.querySelector("script")).toBeNull();
    await expect(canvasElement.querySelector("b")).toBeNull();
    await expect(canvasElement.querySelector(".markdown-view div")).toBeNull();
    await expect(canvasElement).toHaveTextContent("<script>alert(1)</script>");
    await expect(canvasElement).toHaveTextContent("![pic](https://example.com/p.png)");
  },
};

export const LegacyPlainTextStaysReadable: Story = {
  args: { text: "snake_case_name and 2 * 3 * 4\n3. third item typed alone\n\nPlain sentence, no marks." },
  play: async ({ canvasElement }) => {
    await expect(canvasElement).toHaveTextContent("snake_case_name");
    await expect(canvasElement).toHaveTextContent("Plain sentence, no marks.");
    await expect(canvasElement.querySelector("script")).toBeNull();
  },
};

export const DeepNestingStillRenders: Story = {
  args: { text: `${"> ".repeat(40)}deep\n\n${"- ".repeat(40)}item` },
  play: async ({ canvasElement }) => {
    // Deep nesting still renders (the reader's own limit is 100 levels; the server refuses text beyond it).
    await expect(canvasElement).toHaveTextContent("deep");
    await expect(canvasElement).toHaveTextContent("item");
  },
};

export const BlankTextRendersNothing: Story = {
  args: { text: "  \n\n " },
  play: async ({ canvasElement }) => {
    await expect(canvasElement.querySelector(".markdown-view")).toBeNull();
  },
};

export const MermaidBlockIsDrawnAsAnImage: Story = {
  args: { text: `Before\n\n${FLOW}\n\nAfter` },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const image = await canvas.findByRole("img", { name: "Diagram: flowchart" }, { timeout: 20_000 });
    await expect(image.getAttribute("src")).toMatch(/^data:image\/svg\+xml/);
    const svg = decodeURIComponent(image.getAttribute("src") ?? "");
    // Drawn with the shared font, embedded so the image does not depend on the page's fonts.
    await expect(svg).toContain("@font-face");
    await expect(svg).toContain("DejaVu Sans");
    await expect(svg).toContain("Approved?");
    await expect(svg).not.toContain("<script");
    await expect(svg).not.toContain("<foreignObject");
    await expect(canvasElement.querySelector("figure")).toHaveAttribute("data-diagram-state", "drawn");
    // The source stays available as the text alternative.
    await expect(canvas.getByText("Diagram source")).toBeInTheDocument();
    await expect(canvasElement.querySelector("details code")).toHaveTextContent("flowchart LR");
    await expect(canvasElement).toHaveTextContent("Before");
    await expect(canvasElement).toHaveTextContent("After");
  },
};

export const MermaidRedrawsForTheDarkTheme: Story = {
  args: { text: FLOW },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const light = (await canvas.findByRole("img", { name: "Diagram: flowchart" }, { timeout: 20_000 })).getAttribute("src");
    document.documentElement.setAttribute("data-theme", "dark");
    try {
      await waitFor(
        async () => {
          const now = canvas.getByRole("img", { name: "Diagram: flowchart" }).getAttribute("src");
          await expect(now).not.toEqual(light);
        },
        { timeout: 20_000 },
      );
    } finally {
      document.documentElement.setAttribute("data-theme", "light");
    }
  },
};

export const InvalidDiagramShowsSourceAndReason: Story = {
  args: { text: "```mermaid\nthis is not a diagram ???\n```\n\nText after still shows." },
  play: async ({ canvasElement }) => {
    const alert = await within(canvasElement).findByRole("alert", undefined, { timeout: 20_000 });
    await expect(alert).toHaveTextContent("The diagram could not be drawn");
    await expect(canvasElement.querySelector("details")).toHaveAttribute("open");
    await expect(canvasElement.querySelector("details code")).toHaveTextContent("not a diagram");
    await expect(canvasElement).toHaveTextContent("Text after still shows.");
  },
};

export const HostileDiagramCannotRunScript: Story = {
  args: {
    text: '```mermaid\nflowchart LR\n  A["<img src=x onerror=alert(1)>"] --> B["<script>alert(1)</script>"]\n  click A href "javascript:alert(1)"\n```',
  },
  play: async ({ canvasElement }) => {
    const findings = within(canvasElement);
    await waitFor(async () => {
      await expect(canvasElement.querySelector("figure")).not.toHaveAttribute("data-diagram-state", "drawing");
    }, { timeout: 20_000 });
    // Whether drawn or refused, nothing from the text is live on the page, and a drawing carries no script.
    await expect(canvasElement.querySelector("script")).toBeNull();
    await expect(canvasElement.querySelector("img[onerror]")).toBeNull();
    const image = findings.queryByRole("img", { name: "Diagram: flowchart" });
    if (image) {
      const svg = decodeURIComponent(image.getAttribute("src") ?? "");
      await expect(svg).not.toMatch(/<script|onerror|javascript:/i);
    }
  },
};

export const OversizedDiagramIsRefused: Story = {
  args: { text: `\`\`\`mermaid\nflowchart LR\n${"  A --> B\n".repeat(2500)}\`\`\`` },
  play: async ({ canvasElement }) => {
    const alert = await within(canvasElement).findByRole("alert", undefined, { timeout: 20_000 });
    await expect(alert).toHaveTextContent("over the limit");
  },
};

export const RunawayDiagramIsRefused: Story = {
  args: { text: `\`\`\`mermaid\nflowchart LR\n${Array.from({ length: 400 }, (_, i) => `  N${i} --> N${i + 1}`).join("\n")}\n\`\`\`` },
  play: async ({ canvasElement }) => {
    // More edges than the limit: refused, with the source still shown.
    const alert = await within(canvasElement).findByRole("alert", undefined, { timeout: 30_000 });
    await expect(alert).toHaveTextContent("could not be drawn");
  },
};

export const EquationsAreDrawnBesideFormatting: Story = {
  args: {
    math: true,
    text: "The **range** shall satisfy \\( x_1 + y_2 \\) at all times:\n\n$$ \\frac{a}{b} = c_1 * c_2 $$\n\n- item with \\( z^2 \\)",
  },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(canvasElement.querySelectorAll(".math-text")).toHaveLength(3));
    // The underscores and asterisk inside an equation are TeX, not emphasis, and the text around it is still Markdown.
    await expect(canvasElement.querySelector("strong")).toHaveTextContent("range");
    await expect(canvasElement.querySelectorAll("em")).toHaveLength(0);
    await expect(canvasElement.querySelectorAll(".math-text--display")).toHaveLength(1);
    await expect(canvasElement.querySelectorAll("li .math-text")).toHaveLength(1);
  },
};

export const EquationDelimitersAreOrdinaryTextUnlessAsked: Story = {
  args: { text: "Cost is \\( x \\) or $$ y $$ here" },
  play: async ({ canvasElement }) => {
    await expect(canvasElement.querySelector(".math-text")).toBeNull();
    // Without the option the reader's own rules apply: `\\(` is an escaped bracket.
    await expect(canvasElement).toHaveTextContent("Cost is ( x ) or $$ y $$ here");
  },
};

export const EquationsInCodeStayCode: Story = {
  args: { math: true, text: "Write `\\( x \\)` for an inline equation.\n\n```\n$$ not drawn $$\n```" },
  play: async ({ canvasElement }) => {
    await expect(canvasElement.querySelector(".math-text")).toBeNull();
    await expect(canvasElement.querySelector("code")).toHaveTextContent("\\( x \\)");
    await expect(canvasElement.querySelector("pre code")).toHaveTextContent("$$ not drawn $$");
  },
};

export const AnUnclosedOrEmptyEquationStaysText: Story = {
  args: { math: true, text: "Open \\( never closed and $$ $$ empty" },
  play: async ({ canvasElement }) => {
    await expect(canvasElement.querySelector(".math-text")).toBeNull();
    await expect(canvasElement).toHaveTextContent("never closed");
  },
};

export const AnEquationTheReportsRefuseIsShownAsTyped: Story = {
  args: { math: true, text: "Bad \\( \\href{u}{v} \\) equation" },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(canvasElement).toHaveTextContent("\\( \\href{u}{v} \\)"));
    await expect(canvasElement.querySelector(".math-text")).toBeNull();
  },
};

/** Text written before the fields were Markdown: each shape a person plausibly typed must read sensibly. */
export const LegacyPlainTextRegression: Story = {
  args: {
    text: [
      "Applies to file_name_1 and my_variable_name",
      "Cost: 3 * 4 = 12 and 5*6",
      "1. First step",
      "2. Second step",
      "",
      "* not really a list but typed with stars",
      "Tag #urgent and a price of $5 or $10",
      "Use <b>tags</b> & ampersands",
      "Line one",
      "Line two",
    ].join("\n"),
  },
  play: async ({ canvasElement }) => {
    // Underscores inside a word are not emphasis; the words stay as written.
    await expect(canvasElement).toHaveTextContent("file_name_1 and my_variable_name");
    await expect(canvasElement.querySelectorAll("em")).toHaveLength(0);
    // A numbered line is a list item, a starred line a list item, and nothing is lost.
    await expect(canvasElement.querySelector("ol")).toHaveTextContent("First step");
    await expect(canvasElement.querySelector("ul")).toHaveTextContent("not really a list but typed with stars");
    // Raw HTML is text, a hash is not a heading, dollars are not equations, a single line break stays.
    await expect(canvasElement).toHaveTextContent("Use <b>tags</b> & ampersands");
    await expect(canvasElement.querySelector("h3")).toBeNull();
    await expect(canvasElement.querySelector("b")).toBeNull();
    await expect(canvasElement).toHaveTextContent("$5 or $10");
    await expect(canvasElement.querySelectorAll("p br").length).toBeGreaterThan(0);
  },
};
