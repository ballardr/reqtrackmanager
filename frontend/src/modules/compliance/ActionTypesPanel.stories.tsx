import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { ActionTypesPanel } from "./ActionTypesPanel";
import * as complianceApi from "./api";
import type { ComplianceActionType } from "./types";

const ORG_ID = "org-1";

/**
 * `ActionTypesPanel` itself owns no state — `items`/`onReload` are owned by
 * its parent (`ComplianceAdminPanel`, see that component's own
 * `reloadActionTypes`) so the Standards tab's required-action editor can
 * share the same list without the two tabs drifting apart (see this
 * component's own docstring). This harness reproduces that exact
 * "onReload re-fetches and the parent re-renders with fresh items" wiring
 * in isolation, rather than passing a `fn()` that doesn't actually update
 * anything — the same "assert a real round trip" bar `ComplianceAdminPanel
 * .stories.tsx` holds its own stories to.
 *
 * All of `DefinitionList`'s own generic rename/reorder/delete-with-reassign
 * mechanics are already covered by `DefinitionList.stories.tsx` — these
 * stories only exercise what's specific to this panel: that each action
 * wires to the *compliance* action-type endpoints with the right path and
 * payload.
 */
function mockActionTypeApis(initial: ComplianceActionType[]) {
  let items = initial;
  spyOn(api, "get").mockImplementation(async () => items);
  spyOn(api, "post").mockImplementation(async (path: string, body?: unknown) => {
    if (path.endsWith("/action-types")) {
      const payload = body as { name: string };
      const created: ComplianceActionType = { id: `at-${items.length + 1}`, organization_id: ORG_ID, name: payload.name, sort_order: items.length };
      items = [...items, created];
      return created;
    }
    if (path.includes("/move")) {
      const id = path.split("/action-types/")[1].split("/move")[0];
      const direction = (body as { direction: "up" | "down" }).direction;
      const idx = items.findIndex((i) => i.id === id);
      const swapWith = direction === "up" ? idx - 1 : idx + 1;
      if (swapWith >= 0 && swapWith < items.length) {
        const next = [...items];
        [next[idx], next[swapWith]] = [next[swapWith], next[idx]];
        items = next;
      }
      return items.find((i) => i.id === id);
    }
    throw new Error(`unmocked POST: ${path}`);
  });
  spyOn(api, "patch").mockImplementation(async (path: string, body?: unknown) => {
    const id = path.split("/action-types/")[1];
    const payload = body as { name: string };
    items = items.map((i) => (i.id === id ? { ...i, name: payload.name } : i));
    return items.find((i) => i.id === id);
  });
  spyOn(api, "delete").mockImplementation(async (path: string) => {
    const id = path.split("/action-types/")[1].split("?")[0];
    items = items.filter((i) => i.id !== id);
  });
}

function Harness({ initial }: { initial: ComplianceActionType[] }) {
  const [items, setItems] = useState(initial);
  async function reload() {
    setItems(await complianceApi.listActionTypes(ORG_ID));
  }
  return <ActionTypesPanel orgId={ORG_ID} items={items} onReload={reload} />;
}

const meta: Meta<typeof ActionTypesPanel> = {
  title: "Modules/Compliance/ActionTypesPanel",
  component: ActionTypesPanel,
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof ActionTypesPanel>;

export const ListsExistingActionTypes: Story = {
  beforeEach: () => mockActionTypeApis([
    { id: "at-1", organization_id: ORG_ID, name: "Review", sort_order: 0 },
    { id: "at-2", organization_id: ORG_ID, name: "Sign-off", sort_order: 1 },
  ]),
  render: () => <Harness initial={[
    { id: "at-1", organization_id: ORG_ID, name: "Review", sort_order: 0 },
    { id: "at-2", organization_id: ORG_ID, name: "Sign-off", sort_order: 1 },
  ]} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByDisplayValue("Review")).toBeInTheDocument();
    await expect(canvas.getByDisplayValue("Sign-off")).toBeInTheDocument();
  },
};

export const AddActionType: Story = {
  beforeEach: () => mockActionTypeApis([{ id: "at-1", organization_id: ORG_ID, name: "Review", sort_order: 0 }]),
  render: () => <Harness initial={[{ id: "at-1", organization_id: ORG_ID, name: "Review", sort_order: 0 }]} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByPlaceholderText("Action type name"), "Evidence review");
    await userEvent.click(canvas.getByRole("button", { name: "Add action type" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/orgs/${ORG_ID}/modules/compliance/action-types`,
      { name: "Evidence review" }
    ));
    await waitFor(() => expect(canvas.getByDisplayValue("Evidence review")).toBeInTheDocument());
  },
};

export const RenameActionType: Story = {
  beforeEach: () => mockActionTypeApis([{ id: "at-1", organization_id: ORG_ID, name: "Review", sort_order: 0 }]),
  render: () => <Harness initial={[{ id: "at-1", organization_id: ORG_ID, name: "Review", sort_order: 0 }]} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const input = canvas.getByDisplayValue("Review");
    await userEvent.clear(input);
    await userEvent.type(input, "Evidence review");
    await userEvent.click(canvas.getByRole("button", { name: "Rename" }));

    await waitFor(() => expect(api.patch).toHaveBeenCalledWith(
      `/api/v1/orgs/${ORG_ID}/modules/compliance/action-types/at-1`,
      { name: "Evidence review" }
    ));
  },
};

export const MoveActionTypeDown: Story = {
  beforeEach: () => mockActionTypeApis([
    { id: "at-1", organization_id: ORG_ID, name: "Review", sort_order: 0 },
    { id: "at-2", organization_id: ORG_ID, name: "Sign-off", sort_order: 1 },
  ]),
  render: () => <Harness initial={[
    { id: "at-1", organization_id: ORG_ID, name: "Review", sort_order: 0 },
    { id: "at-2", organization_id: ORG_ID, name: "Sign-off", sort_order: 1 },
  ]} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const rows = () => canvas.getAllByRole("textbox");
    await expect(rows()[0]).toHaveValue("Review");

    await userEvent.click(canvas.getAllByRole("button", { name: "Move down" })[0]);

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/orgs/${ORG_ID}/modules/compliance/action-types/at-1/move`,
      { direction: "down" }
    ));
    await waitFor(async () => expect(rows()[0]).toHaveValue("Sign-off"));
  },
};

export const DeleteActionType: Story = {
  beforeEach: () => mockActionTypeApis([
    { id: "at-1", organization_id: ORG_ID, name: "Review", sort_order: 0 },
    { id: "at-2", organization_id: ORG_ID, name: "Sign-off", sort_order: 1 },
  ]),
  render: () => <Harness initial={[
    { id: "at-1", organization_id: ORG_ID, name: "Review", sort_order: 0 },
    { id: "at-2", organization_id: ORG_ID, name: "Sign-off", sort_order: 1 },
  ]} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getAllByRole("button", { name: "Delete action type" })[0]);

    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(
      `/api/v1/orgs/${ORG_ID}/modules/compliance/action-types/at-1`
    ));
    await waitFor(() => expect(canvas.queryByDisplayValue("Review")).not.toBeInTheDocument());
  },
};

export const LightTheme: Story = { ...ListsExistingActionTypes };
export const DarkTheme: Story = { ...ListsExistingActionTypes, globals: { theme: "dark" } };
