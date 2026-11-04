import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import cases from "./mathTexCases.json";
import { mathSource, splitMath, texProblem } from "./mathTex";

/** The TeX check and the equation finder behind `MathText`, run on the vectors the backend test also runs. */
const meta: Meta = { title: "Utils/mathTex", render: () => <p>Pure helpers; see the interactions.</p> };
export default meta;

type Story = StoryObj;

export const SharedVectorsAgreeWithTheBackendCheck: Story = {
  play: async () => {
    for (const { tex, ok } of cases) {
      await expect({ tex, ok: texProblem(tex) === null }).toEqual({ tex, ok });
    }
  },
};

export const RefusalsNameTheProblem: Story = {
  play: async () => {
    await expect(texProblem("\\href{u}{v}")).toBe("The command \\href is not supported in equations.");
    await expect(texProblem("a & b")).toContain("only used inside");
    await expect(texProblem("{a")).toBe("A { is never closed.");
    await expect(texProblem("\\text{<b>}")).toContain("plain text");
  },
};

export const InlineAndDisplayAreFound: Story = {
  play: async () => {
    await expect(splitMath("Let \\(x<y\\) and $$ a=b $$ done")).toEqual([
      { kind: "text", value: "Let " }, { kind: "inline", value: "x<y" }, { kind: "text", value: " and " },
      { kind: "display", value: " a=b " }, { kind: "text", value: " done" },
    ]);
  },
};

export const StrayDelimitersAreText: Story = {
  play: async () => {
    for (const text of ["costs $5 or $6", "an open \\(x", "a lone \\) close", "empty \\(\\) pair", "a single $x$ is not math"]) {
      await expect(splitMath(text)).toEqual([{ kind: "text", value: text }]);
    }
    await expect(splitMath("")).toEqual([]);
  },
};

export const SourceIsWhatWasWritten: Story = {
  play: async () => {
    await expect(mathSource({ kind: "inline", value: "x" })).toBe("\\(x\\)");
    await expect(mathSource({ kind: "display", value: "x" })).toBe("$$x$$");
  },
};
