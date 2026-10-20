import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { PeopleKindIcon } from "./PeopleKindIcon";
import { PEOPLE_KINDS, PEOPLE_KIND_LABEL } from "./peopleRows";

const meta: Meta<typeof PeopleKindIcon> = {
  title: "Modules/Stakeholders/PeopleKindIcon",
  component: PeopleKindIcon,
};
export default meta;

type Story = StoryObj<typeof PeopleKindIcon>;

/** Each kind has its own icon, named by the kind so it is never conveyed by shape or colour alone. */
export const EveryKindIsNamed: Story = {
  render: () => (
    <div className="row">
      {PEOPLE_KINDS.map((kind) => <PeopleKindIcon key={kind} kind={kind} />)}
    </div>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    for (const kind of PEOPLE_KINDS) {
      await expect(canvas.getByRole("img", { name: PEOPLE_KIND_LABEL[kind] })).toBeInTheDocument();
    }
    const shapes = Array.from(canvasElement.querySelectorAll("svg")).map((svg) => svg.innerHTML);
    await expect(new Set(shapes).size).toBe(PEOPLE_KINDS.length);
  },
};

/** Beside text that already names the kind (a chip) the icon is decorative. */
export const UnlabelledIsDecorative: Story = {
  args: { kind: "persona", labelled: false },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("img")).not.toBeInTheDocument();
  },
};
