import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, within } from "storybook/test";

import type { Organization } from "../api/types";
import { FormGrid } from "./FormGrid";
import { LabeledSelect } from "./LabeledSelect";
import { ProjectIdentityFields } from "./ProjectIdentityFields";

const orgs = [{ id: "org-1", name: "Acme Corp" }, { id: "org-2", name: "Beta Inc" }] as Organization[];

const meta: Meta<typeof ProjectIdentityFields> = {
  title: "Components/ProjectIdentityFields",
  component: ProjectIdentityFields,
  args: {
    orgs, orgLabelCap: "Organisation", orgId: "org-1", onOrgChange: fn(),
    name: "", onNameChange: fn(), summary: "", onSummaryChange: fn(),
  },
  render: (args) => (
    <div style={{ width: 640 }}>
      <FormGrid minColumn="18rem"><ProjectIdentityFields {...args} /></FormGrid>
    </div>
  ),
};
export default meta;

type Story = StoryObj<typeof ProjectIdentityFields>;

const template = (
  <LabeledSelect helpNotNeeded label="Create from template" value="" onChange={fn()} options={[{ value: "t1", label: "Standard" }]} placeholder="None" />
);

const top = (el: HTMLElement) => el.getBoundingClientRect().top;
/** Reading order: `a` comes before `b` in the document (they may share a row in the two-column grid). */
const precedes = (a: Element, b: Element) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);

/** Several organisations: the organisation sits alone on the first row, above a rule, then the template, then the name. */
export const OrganisationThenRuleThenTemplateThenName: Story = {
  args: { beforeName: template },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const organisation = canvas.getByLabelText(/Organisation/);
    const rule = canvasElement.querySelector(".form-divider") as HTMLElement;
    const templateSelect = canvas.getByLabelText("Create from template");
    const name = canvas.getByLabelText("Name");
    await expect(rule).not.toBeNull();
    await expect(top(organisation)).toBeLessThan(top(rule));
    await expect(top(rule)).toBeLessThan(top(templateSelect));
    await expect(precedes(templateSelect, name)).toBe(true);
    await expect(organisation).toHaveFocus();
  },
};

/** One organisation: no picker and no rule, and the template (when offered) is the first field. */
export const SingleOrganisationHasNoPickerOrRule: Story = {
  args: { orgs: [orgs[0]], beforeName: template },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByLabelText(/Organisation/)).not.toBeInTheDocument();
    await expect(canvasElement.querySelector(".form-divider")).toBeNull();
    await expect(precedes(canvas.getByLabelText("Create from template"), canvas.getByLabelText("Name"))).toBe(true);
  },
};

/** Import project passes no template: organisation, rule, then the name. */
export const WithoutATemplateSlot: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByLabelText("Create from template")).not.toBeInTheDocument();
    await expect(canvasElement.querySelector(".form-divider")).not.toBeNull();
    await expect(top(canvas.getByLabelText(/Organisation/))).toBeLessThan(top(canvas.getByLabelText("Name")));
  },
};

/** One organisation and no template: the name takes the initial focus. */
export const NameIsFocusedWhenNothingPrecedesIt: Story = {
  args: { orgs: [orgs[0]] },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByLabelText("Name")).toHaveFocus();
  },
};
