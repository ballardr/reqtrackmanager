import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, within } from "storybook/test";

import { withRouter } from "../testing/storybook-helpers";
import { expectStressStable, stressText } from "../testing/stressFixtures";
import { TextStress } from "../testing/TextStress";
import { MarkdownSummary } from "./MarkdownSummary";
import { TileCard, TileGrid } from "./TileCard";

/** A Markdown text as plain words with its equations drawn, clamped to three lines, for a tile, card or list cell. */
const meta: Meta<typeof MarkdownSummary> = {
  title: "Components/MarkdownSummary",
  component: MarkdownSummary,
  decorators: [withRouter("/", "*")],
  render: (args) => <div data-testid="box" style={{ width: 320 }}><MarkdownSummary {...args} /></div>,
};
export default meta;

type Story = StoryObj<typeof MarkdownSummary>;

const MARKS = "We as a company have signed up to ***Paris Agreement*** and we must aim to be *green*.";

export const MarksAreRemovedAndTheWordsKept: Story = {
  args: { text: MARKS, math: true },
  play: async ({ canvasElement }) => {
    const box = within(canvasElement).getByTestId("box");
    await expect(box.textContent).toBe("We as a company have signed up to Paris Agreement and we must aim to be green.");
    await expect(box.textContent).not.toContain("*");
    await expect(box.querySelector("strong, em")).toBeNull();
  },
};

export const EveryMarkIsReadAsWords: Story = {
  args: {
    text: "# Heading\n\n- first **bold** item\n- second [link](https://example.com) item\n\n![the plot](attachment:3f2c9a52-6c1e-4f6e-9b7a-0a1b2c3d4e5f) and `code`\n\n```mermaid\ngraph TD; A-->B\n```",
    math: true,
  },
  play: async ({ canvasElement }) => {
    const box = within(canvasElement).getByTestId("box");
    await expect(box.textContent).toBe("Heading first bold item second link item the plot and code [Diagram]");
    await expect(box.querySelector("a, img, h1, ul, li")).toBeNull();
    await expect(box.textContent).not.toMatch(/[#`*_]|\]\(/);
  },
};

export const InlineAndDisplayEquationsAreDrawnAtInlineSize: Story = {
  args: { text: "The stress \\(\\sigma = F/A\\) holds.\n\n$$ \\sigma_{max} \\leq \\frac{\\sigma_y}{n} $$\n\nEnd.", math: true },
  play: async ({ canvasElement }) => {
    const box = within(canvasElement).getByTestId("box");
    await expect(box.querySelectorAll(".katex").length).toBe(2);
    await expect(box.querySelector(".katex-display")).toBeNull();
    await expect(box.querySelector(".math-text--display")).toBeNull();
    await expect(box.textContent).not.toContain("$");
    await expect(box.textContent).not.toContain("\\(");
    await expect(box.querySelector('annotation[encoding="application/x-tex"]')?.textContent).toBe("\\sigma = F/A");
  },
};

/** Equations are read only where the field holds them. */
export const WithoutMathAnEquationIsNotRead: Story = {
  args: { text: "Range \\( x_1 \\) metres", math: false },
  play: async ({ canvasElement }) => {
    const box = within(canvasElement).getByTestId("box");
    await expect(box.querySelector(".katex")).toBeNull();
  },
};

export const AnEquationKaTeXRefusesIsShownAsWritten: Story = {
  args: { text: "See \\(\\frac{a}\\) and \\(\\input{/etc/passwd}\\) end", math: true },
  play: async ({ canvasElement }) => {
    const box = within(canvasElement).getByTestId("box");
    await expect(box.querySelector(".katex")).toBeNull();
    await expect(box.textContent).toContain("\\frac{a}");
    await expect(box.querySelector("a")).toBeNull();
  },
};

/** A long text stops at three lines whatever it holds, so a tile keeps its height. */
export const ATallEquationDoesNotGrowTheClampedBox: Story = {
  args: {
    text: Array.from({ length: 8 }, () => "stress \\(\\frac{\\frac{a}{b}}{\\frac{c}{d}}\\) and words that fill the line").join(" "),
    math: true,
  },
  play: async ({ canvasElement }) => {
    const box = within(canvasElement).getByTestId("box");
    const summary = box.querySelector<HTMLElement>(".markdown-summary") as HTMLElement;
    const style = getComputedStyle(summary);
    const lineHeight = parseFloat(style.fontSize) * 1.5;
    await expect(summary.getBoundingClientRect().height).toBeLessThanOrEqual(lineHeight * 3 + 1);
    await expect(summary.scrollHeight).toBeGreaterThan(0);
  },
};

export const TheTooltipHoldsPlainTextNeverMarkup: Story = {
  args: { text: `${MARKS} ${"More words follow. ".repeat(20)}and \\(\\sigma = F/A\\)`, math: true },
  play: async ({ canvasElement }) => {
    const summary = canvasElement.querySelector<HTMLElement>(".markdown-summary") as HTMLElement;
    await userEvent.hover(summary);
    const tip = await within(document.body).findByRole("tooltip");
    await expect(tip.textContent).toContain("Paris Agreement and we must");
    await expect(tip.textContent).not.toContain("*");
    await expect(tip.querySelector(".katex")).toBeNull();
  },
};

export const AnEmptyTextDrawsNothing: Story = {
  args: { text: "   ", math: true },
  play: async ({ canvasElement }) => {
    await expect(canvasElement.querySelector(".markdown-summary")).toBeNull();
  },
};

/** Long description text, an unbroken word and an equation in several tiles: every tile keeps its shape. */
export const LongText: Story = {
  render: () => (
    <TextStress
      width={640}
      render={(long) => (
        <TileGrid>
          {[0, 1, 2].map((index) => (
            <TileCard key={index} title={stressText(long, "Reset password")} to="/requirements/1">
              <MarkdownSummary
                text={long
                  ? `**${stressText(long, "", "word")}** ${stressText(long, "", "name")} \\(\\frac{a}{b}\\) ${stressText(long, "", "name")}`
                  : "Short *text* \\(x\\)"}
                math
                className="text-muted"
              />
            </TileCard>
          ))}
        </TileGrid>
      )}
    />
  ),
  play: async ({ canvasElement }) => {
    await expectStressStable(canvasElement);
  },
};
