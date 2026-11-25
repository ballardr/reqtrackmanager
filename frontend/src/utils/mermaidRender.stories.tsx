import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import pkg from "../../package.json";
import config from "./mermaidRenderConfig.json";
import { DiagramError, DIAGRAM_LIMITS, MERMAID_VERSION, renderDiagram } from "./mermaidRender";

/** The diagram renderer's contract with the server's: one engine version and one set of limits. */
const meta: Meta = { title: "Utils/mermaidRender", render: () => <p>Pure helpers; see the interactions.</p> };
export default meta;

type Story = StoryObj;

export const VersionMatchesThePackagePin: Story = {
  play: async () => {
    // The configuration file, the constant and the exact `mermaid` pin in package.json are one version.
    await expect(pkg.dependencies.mermaid).toBe(config.version);
    await expect(MERMAID_VERSION).toBe(config.version);
  },
};

export const DrawsWithinTheLimits: Story = {
  play: async () => {
    const drawn = await renderDiagram("sequenceDiagram\n  A->>B: Hello", "light");
    await expect(drawn.src).toMatch(/^data:image\/svg\+xml/);
    await expect(drawn.width).toBeGreaterThan(0);
    await expect(drawn.height).toBeGreaterThan(0);
    await expect(decodeURIComponent(drawn.src)).toContain("Hello");
  },
};

export const RefusesWhatCannotBeDrawn: Story = {
  play: async () => {
    await expect(renderDiagram("   ", "light")).rejects.toBeInstanceOf(DiagramError);
    await expect(renderDiagram("x".repeat(DIAGRAM_LIMITS.sourceChars + 1), "light")).rejects.toThrow("over the limit");
    await expect(renderDiagram("not a diagram at all", "light")).rejects.toBeInstanceOf(DiagramError);
  },
};
