import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { scopeLabel, scopesForPath } from "./searchScopes";

const LABELS = { project: "This project", all: "All projects" };

/** Lists the scopes that match a path, narrowest first, so the default is the first. */
function Scopes({ path }: { path: string }) {
  return (
    <ol aria-label="scopes">
      {scopesForPath(path, LABELS).map((s) => (
        <li key={s.value}>{`${s.label} [${s.value}]`}</li>
      ))}
    </ol>
  );
}

const meta: Meta<typeof Scopes> = { title: "Modules/searchScopes", component: Scopes };
export default meta;
type Story = StoryObj<typeof Scopes>;

export const OutsideAProjectOnlyAllProjectsApplies: Story = {
  args: { path: "/org-overview" },
  play: async ({ canvasElement }) => {
    const items = within(canvasElement).getAllByRole("listitem");
    await expect(items.map((i) => i.textContent)).toEqual(["All projects [all]"]);
  },
};

export const InAProjectThisProjectIsNarrowest: Story = {
  args: { path: "/projects/p1/requirements" },
  play: async ({ canvasElement }) => {
    const items = within(canvasElement).getAllByRole("listitem");
    await expect(items.map((i) => i.textContent)).toEqual(["This project [project]", "All projects [all]"]);
  },
};

/** A registered module scope (Compliance's standard) is offered, and is the default, on its own pages. */
export const OnAStandardThisStandardIsTheDefault: Story = {
  args: { path: "/standards/3f2c0c4e-0000-4000-8000-000000000001/versions" },
  play: async ({ canvasElement }) => {
    const items = within(canvasElement).getAllByRole("listitem");
    await expect(items[0].textContent).toBe("This standard [compliance:standard:3f2c0c4e-0000-4000-8000-000000000001]");
    await expect(items[items.length - 1].textContent).toBe("All projects [all]");
  },
};

/** The org settings route also starts with /standards/ but names an organisation, not a standard. */
export const StandardSettingsIsNotAStandard: Story = {
  args: { path: "/standards/settings/org1" },
  play: async ({ canvasElement }) => {
    const items = within(canvasElement).getAllByRole("listitem");
    await expect(items.map((i) => i.textContent)).toEqual(["All projects [all]"]);
  },
};

export const LabelsResolveFromTheRegistry: Story = {
  args: { path: "/" },
  play: async () => {
    await expect(scopeLabel("compliance:standard:x", LABELS)).toBe("This standard");
    await expect(scopeLabel("project", LABELS)).toBe("This project");
    await expect(scopeLabel("nosuch:thing:x", LABELS)).toBeNull();
  },
};
