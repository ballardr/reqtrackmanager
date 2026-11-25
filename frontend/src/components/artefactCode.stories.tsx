import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import cases from "./artefactCodeCases.json";
import { splitArtefactCode } from "./artefactCode";

/** The label reader behind the shared link lists, run on the vectors the backend test also runs. */
const meta: Meta = { title: "Components/artefactCode", render: () => <p>Pure helper; see the interactions.</p> };
export default meta;

type Story = StoryObj;

export const SharedVectorsAgreeWithTheBackendRule: Story = {
  play: async () => {
    for (const { label, code, title } of cases) {
      await expect({ label, ...splitArtefactCode(label) }).toEqual({ label, code, title });
    }
  },
};
