import type { Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter } from "react-router-dom";
import { expect, within } from "storybook/test";

import { ClearButton } from "../../components/ClearButton";
import { expectStressStable, stressText, STRESS_TEXT } from "../../testing/stressFixtures";
import { TextStress } from "../../testing/TextStress";
import { PeopleKindLabel } from "./PeopleKindLabel";
import { PERSON_KIND_LABEL, type PersonKind } from "./peopleRows";

const KINDS: PersonKind[] = ["persona", "stakeholder", "group", "anonymous"];

const meta: Meta<typeof PeopleKindLabel> = {
  title: "Modules/Stakeholders/PeopleKindLabel",
  component: PeopleKindLabel,
  decorators: [(Story) => <MemoryRouter><Story /></MemoryRouter>],
};
export default meta;

type Story = StoryObj<typeof PeopleKindLabel>;

/** Every kind draws its own icon, named by the kind, beside the name; the anonymous participant's icon differs from the other three. */
export const EveryKindShowsItsIconAndName: Story = {
  render: () => (
    <div className="stack">
      {KINDS.map((kind) => <PeopleKindLabel key={kind} kind={kind} name={`${kind} name`} />)}
    </div>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    for (const kind of KINDS) {
      await expect(canvas.getByRole("img", { name: PERSON_KIND_LABEL[kind] })).toBeInTheDocument();
      await expect(canvas.getByText(`${kind} name`)).toBeInTheDocument();
    }
    const shapes = Array.from(canvasElement.querySelectorAll("svg")).map((svg) => svg.innerHTML);
    await expect(new Set(shapes).size).toBe(KINDS.length);
  },
};

/** With a route the name is a link; a code and a note sit either side of it. */
export const LinkWithCodeAndNote: Story = {
  args: {
    kind: "persona", name: "Field Technician", to: "/personas/1",
    before: <span className="text-muted">PER-001</span>, after: <span className="text-muted">via a participant</span>,
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("link", { name: "Field Technician" })).toHaveAttribute("href", "/personas/1");
    await expect(canvas.getByText("PER-001")).toBeInTheDocument();
    await expect(canvas.getByText("via a participant")).toBeInTheDocument();
  },
};

/** Long and unbroken names in removable chips (stretched to one column so the rows can be compared) stay on one line each: the icon and the remove control keep their place. */
export const LongText: Story = {
  render: () => (
    <TextStress
      width={420}
      render={(long) => (
        <ul className="removable-list" style={{ flexDirection: "column", alignItems: "stretch" }}>
          {KINDS.map((kind, index) => (
            <li key={kind} className="removable-item" data-stress-row>
              <span style={{ flex: "1 1 auto", minWidth: 0, display: "flex" }}>
              <PeopleKindLabel
                kind={kind}
                name={stressText(long, `Short ${index}`, index % 2 ? "word" : "name")}
                to={index < 3 ? `/x/${kind}` : undefined}
                before={long ? <span>{STRESS_TEXT.code}</span> : undefined}
              />
              </span>
              <ClearButton label={`Remove ${kind}`} onClick={() => undefined} />
            </li>
          ))}
        </ul>
      )}
    />
  ),
  play: async ({ canvasElement }) => {
    await expectStressStable(canvasElement);
    const long = canvasElement.querySelector<HTMLElement>('[data-stress="long"]')!;
    for (const item of Array.from(long.querySelectorAll<HTMLElement>(".removable-item"))) {
      await expect(item.getBoundingClientRect().right).toBeLessThanOrEqual(long.getBoundingClientRect().right + 1);
    }
  },
};
