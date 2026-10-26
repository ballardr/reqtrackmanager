import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { MathText } from "./MathText";

/** Text with equations drawn by KaTeX, as shown for a requirement's description, reasoning and clarification. */
const meta: Meta<typeof MathText> = {
  title: "Components/MathText",
  component: MathText,
  render: (args) => <p data-testid="text"><MathText {...args} /></p>,
};
export default meta;

type Story = StoryObj<typeof MathText>;

export const InlineAndDisplayEquationsAreDrawn: Story = {
  args: { text: "The stress \\(\\sigma = F/A\\) holds. $$ \\sigma_{max} \\leq \\frac{\\sigma_y}{n} $$ End." },
  play: async ({ canvasElement }) => {
    const text = within(canvasElement).getByTestId("text");
    await expect(text.querySelectorAll(".katex").length).toBe(2);
    await expect(text.querySelectorAll(".katex-display").length).toBe(1);
    await expect(text.querySelector('annotation[encoding="application/x-tex"]')?.textContent).toBe("\\sigma = F/A");
    await expect(text.textContent).toContain("The stress");
    await expect(text.querySelector(".math-text--display")).not.toBeNull();
  },
};

export const OrdinaryTextIsUnchanged: Story = {
  args: { text: "Costs $5 and a stray \\(open, with <b>markup</b>." },
  play: async ({ canvasElement }) => {
    const text = within(canvasElement).getByTestId("text");
    await expect(text.textContent).toBe("Costs $5 and a stray \\(open, with <b>markup</b>.");
    await expect(text.querySelector("b")).toBeNull();
    await expect(text.querySelector(".katex")).toBeNull();
  },
};

/** What a report refuses is shown as written here too, never drawn and never a link. */
export const RefusedTexIsShownAsWritten: Story = {
  args: { text: "See \\(\\href{http://example.com}{x}\\) and \\(\\input{/etc/passwd}\\) and $$ \\frac{a} $$." },
  play: async ({ canvasElement }) => {
    const text = within(canvasElement).getByTestId("text");
    await expect(text.querySelector(".katex")).toBeNull();
    await expect(text.querySelector("a")).toBeNull();
    await expect(text.textContent).toBe("See \\(\\href{http://example.com}{x}\\) and \\(\\input{/etc/passwd}\\) and $$ \\frac{a} $$.");
  },
};

export const HostileMarkupInsideAnEquationNeverReachesThePage: Story = {
  args: { text: "\\(\\text{<img src=x onerror=alert(1)>}\\) and \\(x\\)<script>window.__pwned = 1</script>" },
  play: async ({ canvasElement }) => {
    const text = within(canvasElement).getByTestId("text");
    await expect(text.querySelector("img")).toBeNull();
    await expect(text.querySelector("script")).toBeNull();
    await expect((window as unknown as { __pwned?: number }).__pwned).toBeUndefined();
    await expect(text.querySelectorAll(".katex").length).toBe(1); // the safe `\(x\)`
  },
};

export const AnEquationReadsToAScreenReaderAsMathML: Story = {
  args: { text: "\\(\\frac{a}{b}\\)" },
  play: async ({ canvasElement }) => {
    const mathml = within(canvasElement).getByTestId("text").querySelector("math");
    await expect(mathml).not.toBeNull();
    await expect(mathml?.querySelector("mfrac")).not.toBeNull();
  },
};
