import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { DecisionTemplatesPanel } from "./DecisionTemplatesPanel";
import type { DecisionTemplate } from "./types";

const ORG_ID = "org-1";

function template(overrides: Partial<DecisionTemplate> = {}): DecisionTemplate {
  return {
    id: "template-1", organization_id: ORG_ID, name: "Nygard (Classic ADR)",
    description: "Michael Nygard's original minimal format.", context_prompt: "What is the issue?",
    options_considered_prompt: null, chosen_option_prompt: null, rationale_prompt: null,
    consequences_prompt: null, assumptions_prompt: null, constraints_prompt: null, sort_order: 0,
    ...overrides,
  };
}

function mockTemplateApis(initial: DecisionTemplate[]) {
  let items = initial;
  spyOn(api, "get").mockImplementation(async () => items);
  spyOn(api, "post").mockImplementation(async (_path: string, body?: unknown) => {
    const created = { id: `template-${items.length + 1}`, organization_id: ORG_ID, sort_order: items.length, ...(body as object) } as DecisionTemplate;
    items = [...items, created];
    return created;
  });
  spyOn(api, "patch").mockImplementation(async (path: string, body?: unknown) => {
    const id = path.split("/templates/")[1];
    items = items.map((t) => (t.id === id ? { ...t, ...(body as object) } as DecisionTemplate : t));
    return items.find((t) => t.id === id);
  });
  spyOn(api, "delete").mockImplementation(async (path: string) => {
    const id = path.split("/templates/")[1];
    items = items.filter((t) => t.id !== id);
  });
}

const meta: Meta<typeof DecisionTemplatesPanel> = {
  title: "Modules/Decisions/DecisionTemplatesPanel",
  component: DecisionTemplatesPanel,
  args: { orgId: ORG_ID },
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof DecisionTemplatesPanel>;

export const ListsExistingTemplates: Story = {
  beforeEach: () => mockTemplateApis([template(), template({ id: "template-2", name: "MADR" })]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Nygard (Classic ADR)")).toBeInTheDocument());
    await expect(canvas.getByText("MADR")).toBeInTheDocument();
  },
};

export const EmptyState: Story = {
  beforeEach: () => mockTemplateApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No Decision Templates yet.")).toBeInTheDocument());
  },
};

// `New decision template`/`Delete "..."` both open a `Modal`/`ConfirmDialog`,
// which portal to `document.body` (`createPortal`) — so the button that
// opens them is queried from `canvas` (still inside this panel's own DOM
// subtree), but everything inside the dialog itself is queried from
// `within(document.body)` instead, mirroring `DecisionFormModal.stories
// .tsx`'s own convention.
export const CreateTemplate: Story = {
  beforeEach: () => mockTemplateApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    await waitFor(() => canvas.getByRole("button", { name: "New decision template" }));
    await userEvent.click(canvas.getByRole("button", { name: "New decision template" }));
    await userEvent.type(body.getByLabelText("Template name"), "Y-Statement");
    await userEvent.click(body.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/orgs/${ORG_ID}/modules/decisions/templates`,
      expect.objectContaining({ name: "Y-Statement" })
    ));
    await waitFor(() => expect(canvas.getByText("Y-Statement")).toBeInTheDocument());
  },
};

export const DeleteTemplate: Story = {
  beforeEach: () => mockTemplateApis([template()]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    await waitFor(() => canvas.getByRole("button", { name: 'Delete "Nygard (Classic ADR)"' }));
    await userEvent.click(canvas.getByRole("button", { name: 'Delete "Nygard (Classic ADR)"' }));
    await userEvent.click(body.getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(
      `/api/v1/orgs/${ORG_ID}/modules/decisions/templates/template-1`
    ));
    await waitFor(() => expect(canvas.queryByText("Nygard (Classic ADR)")).not.toBeInTheDocument());
  },
};

export const LightTheme: Story = { ...ListsExistingTemplates };
export const DarkTheme: Story = { ...ListsExistingTemplates, globals: { theme: "dark" } };
