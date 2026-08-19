import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { ApiError } from "../api/client";
import { DefinitionList } from "./DefinitionList";

interface Named {
  id: string;
  name: string;
}

function SingleFieldHarness({
  initialItems,
  onDeleteConflictFor,
}: {
  initialItems: Named[];
  onDeleteConflictFor?: string;
}) {
  const [items, setItems] = useState(initialItems);
  return (
    <DefinitionList<Named>
      items={items}
      fields={[{ key: "name", getValue: (i) => i.name, placeholder: "Name", maxWidth: 220 }]}
      getReassignLabel={(i) => i.name}
      onMove={fn(async (id, direction) => {
        setItems((prev) => {
          const idx = prev.findIndex((i) => i.id === id);
          const swapWith = direction === "up" ? idx - 1 : idx + 1;
          if (swapWith < 0 || swapWith >= prev.length) return prev;
          const next = [...prev];
          [next[idx], next[swapWith]] = [next[swapWith], next[idx]];
          return next;
        });
      })}
      onRename={fn(async (id, values) => {
        setItems((prev) => prev.map((i) => (i.id === id ? { ...i, name: values.name } : i)));
      })}
      onAdd={fn(async (values) => {
        setItems((prev) => [...prev, { id: `new-${prev.length}`, name: values.name }]);
      })}
      onDelete={fn(async (id, reassignToId) => {
        if (id === onDeleteConflictFor && !reassignToId) {
          throw new ApiError(409, "2 action items still use this type");
        }
        setItems((prev) => prev.filter((i) => i.id !== id));
      })}
      deleteLabel="Delete type"
      addLabel="New type"
    />
  );
}

const meta: Meta<typeof DefinitionList> = {
  title: "Components/DefinitionList",
  component: DefinitionList,
};
export default meta;

type Story = StoryObj<typeof DefinitionList>;

export const RenameReorderAndDelete: Story = {
  render: () => (
    <SingleFieldHarness
      initialItems={[
        { id: "1", name: "Bug" },
        { id: "2", name: "Feature" },
        { id: "3", name: "Chore" },
      ]}
    />
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);

    // Reorder: move "Feature" up, ahead of "Bug".
    const rows = () => canvas.getAllByRole("textbox");
    await expect(rows()[0]).toHaveValue("Bug");
    const upButtons = canvas.getAllByRole("button", { name: "Move up" });
    await userEvent.click(upButtons[1]);
    await waitFor(async () => expect(rows()[0]).toHaveValue("Feature"));

    // Rename: edit "Chore" and save via the pencil button that appears once dirty.
    const choreInput = rows().find((el) => (el as HTMLInputElement).value === "Chore")!;
    await userEvent.clear(choreInput);
    await userEvent.type(choreInput, "Task");
    await userEvent.click(canvas.getByRole("button", { name: "Rename" }));
    await waitFor(async () => expect(canvas.queryByDisplayValue("Chore")).not.toBeInTheDocument());
    await expect(canvas.getByDisplayValue("Task")).toBeInTheDocument();

    // Delete an item with no dependents: disappears immediately. (2 remaining
    // items + the always-present "add new" row's own input = 3 textboxes.)
    const deleteButtons = canvas.getAllByRole("button", { name: "Delete type" });
    await userEvent.click(deleteButtons[0]);
    await waitFor(async () => expect(rows()).toHaveLength(3));
  },
};

export const DeleteLastItemIsDisabled: Story = {
  render: () => <SingleFieldHarness initialItems={[{ id: "1", name: "Only type" }]} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("button", { name: "This is the only one — create another first so there's something to reassign to." })
    ).toBeDisabled();
  },
};

export const DeleteInUseOffersReassignThenConfirms: Story = {
  render: () => (
    <SingleFieldHarness
      initialItems={[
        { id: "1", name: "Bug" },
        { id: "2", name: "Feature" },
      ]}
      onDeleteConflictFor="1"
    />
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getAllByRole("button", { name: "Delete type" })[0]);

    await expect(await canvas.findByText("2 action items still use this type")).toBeInTheDocument();
    const confirmButton = canvas.getByRole("button", { name: "Confirm delete" });
    await expect(confirmButton).toBeDisabled();

    const select = canvas.getByRole("combobox");
    await userEvent.selectOptions(select, "Feature");
    await expect(confirmButton).toBeEnabled();

    await userEvent.click(confirmButton);
    await waitFor(async () => expect(canvas.queryByText("2 action items still use this type")).not.toBeInTheDocument());
    // 1 remaining item + the "add new" row's own input = 2 textboxes.
    await expect(canvas.getAllByRole("textbox")).toHaveLength(2);
  },
};

export const AddDisabledUntilFilled: Story = {
  render: () => <SingleFieldHarness initialItems={[{ id: "1", name: "Bug" }]} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const addButton = canvas.getByRole("button", { name: "New type" });
    await expect(addButton).toBeDisabled();

    await userEvent.type(canvas.getByPlaceholderText("Name"), "Task");
    await expect(addButton).toBeEnabled();
    await userEvent.click(addButton);
    // 2 items + the "add new" row's own (now-cleared) input = 3 textboxes.
    await waitFor(async () => expect(canvas.getAllByRole("textbox")).toHaveLength(3));
  },
};

interface LinkTypeLike {
  id: string;
  forward_name: string;
  reverse_name: string;
}

export const TwoFieldVariant: Story = {
  render: () => {
    function Harness() {
      const [items, setItems] = useState<LinkTypeLike[]>([
        { id: "1", forward_name: "blocks", reverse_name: "is blocked by" },
        { id: "2", forward_name: "relates to", reverse_name: "relates to" },
      ]);
      return (
        <DefinitionList<LinkTypeLike>
          items={items}
          fields={[
            { key: "forward", getValue: (i) => i.forward_name, placeholder: "Forward name", ariaLabel: "Forward name", maxWidth: 200 },
            { key: "reverse", getValue: (i) => i.reverse_name, placeholder: "Reverse name", ariaLabel: "Reverse name", maxWidth: 200 },
          ]}
          getReassignLabel={(i) => i.forward_name}
          onMove={fn(async () => {})}
          onRename={fn(async () => {})}
          onAdd={fn(async (values) => {
            setItems((prev) => [...prev, { id: `new-${prev.length}`, forward_name: values.forward, reverse_name: values.reverse }]);
          })}
          onDelete={fn(async () => {})}
          deleteLabel="Delete link type"
          addLabel="New link type"
        />
      );
    }
    return <Harness />;
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // 2 items + the "add new" row's own forward-name field = 3.
    await expect(canvas.getAllByLabelText("Forward name")).toHaveLength(3);
    const addButton = canvas.getByRole("button", { name: "New link type" });
    await expect(addButton).toBeDisabled();

    await userEvent.type(canvas.getByPlaceholderText("Forward name"), "depends on");
    await expect(addButton).toBeDisabled();
    await userEvent.type(canvas.getByPlaceholderText("Reverse name"), "is depended on by");
    await expect(addButton).toBeEnabled();

    await userEvent.click(addButton);
    await waitFor(async () => expect(canvas.getAllByLabelText("Forward name")).toHaveLength(4));
  },
};

export const LightTheme: Story = { ...RenameReorderAndDelete };
export const DarkTheme: Story = { ...RenameReorderAndDelete, globals: { theme: "dark" } };
