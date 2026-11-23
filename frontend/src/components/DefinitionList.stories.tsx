import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, fireEvent, fn, screen, userEvent, waitFor, within } from "storybook/test";

import { ApiError } from "../api/client";
import { requiredCaptions } from "../testing/requiredMarkers";
import { openAddDialog } from "../testing/storybook-helpers";
import { expectStressStable, stressText } from "../testing/stressFixtures";
import { TextStress } from "../testing/TextStress";
import { CellText } from "./CellText";
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

    // Delete an item with no dependents: it disappears immediately, and the list shows no empty add fields.
    const deleteButtons = canvas.getAllByRole("button", { name: "Delete type" });
    await userEvent.click(deleteButtons[0]);
    await waitFor(async () => expect(rows()).toHaveLength(2));
  },
};

export const DeleteLastItemIsDisabled: Story = {
  render: () => <SingleFieldHarness initialItems={[{ id: "1", name: "Only type" }]} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("button", { name: "This is the only one — create another first so there is something to reassign to." })
    ).toBeDisabled();
  },
};

export const DeleteInUseOpensDialogThenConfirms: Story = {
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

    // The dialog renders in a portal, outside the story canvas.
    const dialog = within(await within(document.body).findByRole("dialog", { name: "Delete “Bug”?" }));
    await expect(dialog.getByText("2 action items still use this type")).toBeInTheDocument();
    const confirmButton = dialog.getByRole("button", { name: "Confirm delete" });
    await expect(confirmButton).toBeDisabled();

    await userEvent.selectOptions(dialog.getByRole("combobox", { name: "Reassign existing items to" }), "Feature");
    await expect(confirmButton).toBeEnabled();

    await userEvent.click(confirmButton);
    await waitFor(() => expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument());
    await expect(canvas.getAllByRole("textbox")).toHaveLength(1);
  },
};

/** The list shows no empty fields: Add opens a dialog whose Add button waits for the required field. */
export const AddOpensADialogAndWaitsForTheRequiredField: Story = {
  render: () => <SingleFieldHarness initialItems={[{ id: "1", name: "Bug" }]} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getAllByRole("textbox")).toHaveLength(1);
    const dialog = await openAddDialog(canvas, "New type");
    const save = dialog.getByRole("button", { name: "Add" });
    await expect(dialog.getByRole("textbox", { name: "Name" })).toBeInTheDocument();
    await expect(save).toBeDisabled();

    await userEvent.type(dialog.getByRole("textbox", { name: "Name" }), "Task");
    await expect(save).toBeEnabled();
    await userEvent.click(save);
    await waitFor(async () => expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument());
    await expect(canvas.getByDisplayValue("Task")).toBeInTheDocument();
  },
};

/** A refused add stays in the dialog beside Add, with what was typed. */
export const ARefusedAddStaysInTheDialog: Story = {
  render: () => {
    function Harness() {
      return (
        <DefinitionList<Named>
          items={[{ id: "1", name: "Bug" }]}
          fields={[{ key: "name", getValue: (i) => i.name, placeholder: "Name" }]}
          getReassignLabel={(i) => i.name}
          onRename={async () => {}}
          onAdd={async () => { throw new Error("That name is already used."); }}
          onDelete={async () => {}}
          deleteLabel="Delete type"
          addLabel="New type"
        />
      );
    }
    return <Harness />;
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const dialog = await openAddDialog(canvas, "New type");
    await userEvent.type(dialog.getByRole("textbox", { name: "Name" }), "Bug");
    await userEvent.click(dialog.getByRole("button", { name: "Add" }));
    await expect(await dialog.findByText("That name is already used.")).toBeInTheDocument();
    await expect(dialog.getByRole("textbox", { name: "Name" })).toHaveValue("Bug");
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
    // The two rows only: the empty fields are in the dialog.
    await expect(canvas.getAllByLabelText("Forward name")).toHaveLength(2);
    const dialog = await openAddDialog(canvas, "New link type");
    const addButton = dialog.getByRole("button", { name: "Add" });
    await expect(addButton).toBeDisabled();

    await userEvent.type(dialog.getByRole("textbox", { name: "Forward name" }), "depends on");
    await expect(addButton).toBeDisabled();
    await userEvent.type(dialog.getByRole("textbox", { name: "Reverse name" }), "is depended on by");
    await expect(addButton).toBeEnabled();

    await userEvent.click(addButton);
    await waitFor(async () => expect(canvas.getAllByLabelText("Forward name")).toHaveLength(3));
  },
};

interface FlaggedItem {
  id: string;
  name: string;
  enabled: boolean;
}

/**
 * `renderExtra`: a per-row slot for an attribute the list's text-only `fields` cannot express (the Compliance
 * mapping-relationship type's boolean), rendered between the text fields and the reorder/delete buttons.
 */
export const WithRenderExtra: Story = {
  render: () => {
    function Harness() {
      const [items, setItems] = useState<FlaggedItem[]>([{ id: "1", name: "Equivalent", enabled: false }]);
      return (
        <DefinitionList<FlaggedItem>
          items={items}
          fields={[{ key: "name", getValue: (i) => i.name, placeholder: "Name", ariaLabel: "Name" }]}
          getReassignLabel={(i) => i.name}
          onMove={fn(async () => {})}
          onRename={fn(async () => {})}
          onAdd={fn(async () => {})}
          onDelete={fn(async () => {})}
          deleteLabel="Delete"
          addLabel="Add"
          renderExtra={(item) => (
            <label key="flag" className="row" style={{ gap: "0.3rem" }}>
              <input
                type="checkbox"
                aria-label={`Enabled for ${item.name}`}
                checked={item.enabled}
                onChange={(e) => {
                  const checked = e.target.checked;
                  setItems((prev) => prev.map((i) => (i.id === item.id ? { ...i, enabled: checked } : i)));
                }}
              />
              Enabled
            </label>
          )}
        />
      );
    }
    return <Harness />;
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const checkbox = canvas.getByLabelText("Enabled for Equivalent");
    await expect(checkbox).not.toBeChecked();
    await userEvent.click(checkbox);
    await expect(checkbox).toBeChecked();
  },
};

/** Derived order (no `onMove`), a numeric field, an optional field, and a
 * two-item floor — the shape scoring levels use. */
export const DerivedOrderWithFloorAndOptionalField: Story = {
  render: () => {
    function Harness() {
      const [items, setItems] = useState([
        { id: "a", name: "Low", weight: "1", note: "" },
        { id: "b", name: "High", weight: "3", note: "Strong evidence" },
      ]);
      return (
        <DefinitionList<{ id: string; name: string; weight: string; note: string }>
          items={items}
          minItems={2}
          fields={[
            { key: "name", getValue: (i) => i.name, placeholder: "Name", ariaLabel: "Level name" },
            { key: "weight", getValue: (i) => i.weight, placeholder: "Weight", ariaLabel: "Level weight", inputType: "number" },
            { key: "note", getValue: (i) => i.note, placeholder: "Guidance", ariaLabel: "Level guidance", optional: true },
          ]}
          getReassignLabel={(i) => i.name}
          onRename={async () => {}}
          onAdd={async (values) => {
            setItems((prev) => [...prev, { id: `n${prev.length}`, name: values.name, weight: values.weight, note: values.note }]);
          }}
          onDelete={async (id) => setItems((prev) => prev.filter((i) => i.id !== id))}
          deleteLabel="Delete level"
          addLabel="Add level"
        />
      );
    }
    return <Harness />;
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("button", { name: "Move up" })).not.toBeInTheDocument();
    await expect(canvas.getAllByRole("button", { name: /At least 2 are required/ })).toHaveLength(2);
    // The optional guidance field may stay blank (no `*`); weight is a number input.
    const dialog = await openAddDialog(canvas, "Add level");
    await expect(dialog.getByRole("textbox", { name: "Guidance" })).toBeInTheDocument();
    await expect(requiredCaptions(document.body)).toEqual(["Name", "Weight"]);
    await userEvent.type(dialog.getByRole("textbox", { name: "Name" }), "Mid");
    await userEvent.type(dialog.getByRole("spinbutton", { name: "Weight" }), "2");
    await expect(dialog.getByRole("spinbutton", { name: "Weight" })).toHaveAttribute("type", "number");
    await userEvent.click(dialog.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(canvas.getAllByRole("button", { name: "Delete level" })).toHaveLength(3));
  },
};

/** A long free-text field (`multiline`) is a growing text area in the row and in the add form. */
export const MultilineFieldGrowsWithContent: Story = {
  render: () => {
    function Harness() {
      const [items, setItems] = useState([{ id: "a", name: "Market", definition: "Buyers and competitors." }]);
      return (
        <DefinitionList<{ id: string; name: string; definition: string }>
          items={items}
          fields={[
            { key: "name", getValue: (i) => i.name, placeholder: "Name", ariaLabel: "Type name" },
            { key: "definition", getValue: (i) => i.definition, placeholder: "Definition", ariaLabel: "Type definition", multiline: true, optional: true },
          ]}
          getReassignLabel={(i) => i.name}
          onRename={async (id, values) => setItems((prev) => prev.map((i) => (i.id === id ? { ...i, ...values } : i)))}
          onAdd={async (values) => {
            setItems((prev) => [...prev, { id: `n${prev.length}`, name: values.name, definition: values.definition }]);
          }}
          onDelete={async (id) => setItems((prev) => prev.filter((i) => i.id !== id))}
          deleteLabel="Delete type"
          addLabel="Add type"
        />
      );
    }
    return <Harness />;
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const box = canvas.getByRole("textbox", { name: "Type definition" });
    await expect(box.tagName).toBe("TEXTAREA");
    const before = (box as HTMLElement).clientHeight;
    fireEvent.change(box, { target: { value: Array.from({ length: 6 }, (_, i) => `Line ${i + 1}`).join("\n") } });
    await waitFor(() => expect((box as HTMLElement).clientHeight).toBeGreaterThan(before));
    // The optional definition may stay blank when adding; it is a growing text area there too.
    const dialog = await openAddDialog(canvas, "Add type");
    await expect(dialog.getByRole("textbox", { name: "Definition" }).tagName).toBe("TEXTAREA");
    await userEvent.type(dialog.getByRole("textbox", { name: "Name" }), "User");
    await userEvent.click(dialog.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(canvas.getByDisplayValue("User")).toBeInTheDocument());
  },
};

export const PerRowDeleteLabelAndConfirmation: Story = {
  render: () => {
    function Harness() {
      const [items, setItems] = useState<Named[]>([
        { id: "org", name: "Organisation default" },
        { id: "own", name: "Own row" },
      ]);
      return (
        <DefinitionList<Named>
          items={items}
          fields={[{ key: "name", getValue: (i) => i.name, placeholder: "Name" }]}
          getReassignLabel={(i) => i.name}
          onRename={async () => {}}
          onAdd={async () => {}}
          onDelete={async (id) => setItems((prev) => prev.filter((i) => i.id !== id))}
          deleteLabel="Delete type"
          getDeleteLabel={(i) => (i.id === "org" ? "Hide type in this project" : "Delete type")}
          confirmDelete={(i) =>
            i.id === "org" ? { title: `Hide "${i.name}"?`, message: "It can be added back.", confirmLabel: "Hide" } : null
          }
          minItems={0}
          addLabel="New type"
        />
      );
    }
    return <Harness />;
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // A row with a confirmation asks first, and Cancel leaves it in place.
    await userEvent.click(canvas.getByRole("button", { name: "Hide type in this project" }));
    await userEvent.click(within(await screen.findByRole("dialog", { name: 'Hide "Organisation default"?' })).getByRole("button", { name: "Cancel" }));
    await expect(canvas.getByDisplayValue("Organisation default")).toBeInTheDocument();
    // Confirming deletes it; a row without a confirmation deletes at once, down to an empty list.
    await userEvent.click(canvas.getByRole("button", { name: "Hide type in this project" }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Hide" }));
    await waitFor(() => expect(canvas.queryByDisplayValue("Organisation default")).not.toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Delete type" }));
    await waitFor(() => expect(canvas.queryByDisplayValue("Own row")).not.toBeInTheDocument());
  },
};

export const LightTheme: Story = { ...RenameReorderAndDelete };
export const DarkTheme: Story = { ...RenameReorderAndDelete, globals: { theme: "dark" } };

interface Level {
  id: string;
  name: string;
  weight: number;
  guidance: string;
}

/** `layout="grid"`: one heading per field, every row aligned under it, and a Rename that only shows once a row is edited. */
function GridHarness() {
  const [items, setItems] = useState<Level[]>([
    { id: "1", name: "Low", weight: 1, guidance: "A handful of people." },
    { id: "2", name: "High", weight: 2, guidance: "" },
  ]);
  return (
      <DefinitionList<Level>
        layout="grid"
        items={items}
        fields={[
          { key: "name", getValue: (l) => l.name, label: "Level", placeholder: "Level name", ariaLabel: "Level name", track: "minmax(8rem, 1fr)" },
          { key: "weight", getValue: (l) => String(l.weight), label: "Weight", placeholder: "Weight", ariaLabel: "Level weight", track: "6rem", inputType: "number" },
          { key: "guidance", getValue: (l) => l.guidance, label: "Guidance", placeholder: "Guidance", ariaLabel: "Level guidance", track: "minmax(10rem, 2fr)", optional: true, multiline: true },
        ]}
        getReassignLabel={(l) => l.name}
        minItems={1}
        onRename={fn(async (id, values) => {
          setItems((prev) => prev.map((l) => (l.id === id ? { ...l, name: values.name, guidance: values.guidance } : l)));
        })}
        onAdd={fn(async (values) => {
          setItems((prev) => [...prev, { id: `new-${prev.length}`, name: values.name, weight: Number(values.weight), guidance: values.guidance }]);
        })}
        onDelete={fn(async (id) => {
          setItems((prev) => prev.filter((l) => l.id !== id));
        })}
        deleteLabel="Delete level"
        addLabel="Add level"
      />
  );
}

export const GridLayoutAlignsRowsUnderHeadings: Story = {
  render: () => <GridHarness />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Guidance")).toBeInTheDocument();
    // Nothing to save yet, so no Rename is offered.
    await expect(canvas.queryByRole("button", { name: "Rename" })).not.toBeInTheDocument();
    const names = canvas.getAllByRole("textbox", { name: "Level name" });
    await userEvent.clear(names[0]);
    await userEvent.type(names[0], "Minor");
    await userEvent.click(canvas.getByRole("button", { name: "Rename" }));
    await waitFor(() => expect(canvas.getByDisplayValue("Minor")).toBeInTheDocument());
    // The grid holds only the items; the new one is made in the Add dialog.
    await expect(canvas.getAllByRole("textbox", { name: "Level name" })).toHaveLength(2);
    const dialog = await openAddDialog(canvas, "Add level");
    await userEvent.type(dialog.getByRole("textbox", { name: "Level" }), "Top");
    await userEvent.type(dialog.getByRole("spinbutton", { name: "Weight" }), "5");
    await userEvent.click(dialog.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(canvas.getByDisplayValue("Top")).toBeInTheDocument());
  },
};

/** `isReadOnly` (grid layout): a row that cannot be renamed here has unavailable inputs and no Rename button, but can still be deleted. */
export const GridReadOnlyRowCannotBeRenamed: Story = {
  render: () => (
    <DefinitionList<Named>
      layout="grid"
      items={[{ id: "org", name: "Organisation default" }, { id: "own", name: "Project type" }]}
      fields={[{ key: "name", getValue: (i) => i.name, label: "Name", placeholder: "Type name", ariaLabel: "Type name" }]}
      getReassignLabel={(i) => i.name}
      isReadOnly={(i) => i.id === "org"}
      minItems={0}
      onRename={fn(async () => {})}
      onAdd={fn(async () => {})}
      onDelete={fn(async () => {})}
      deleteLabel="Delete type"
      addLabel="Add type"
    />
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const [locked, editable] = canvas.getAllByRole("textbox", { name: "Type name" }) as HTMLInputElement[];
    await expect(locked).toBeDisabled();
    await expect(editable).toBeEnabled();
    await userEvent.type(editable, "!");
    await expect(canvas.getAllByRole("button", { name: "Rename" })).toHaveLength(1);
    await expect(canvas.getAllByRole("button", { name: "Delete type" })).toHaveLength(2);
  },
};

interface Summarised {
  id: string;
  name: string;
  summary: string;
}

/**
 * The Connection Types shape: a name, then per-row text (a summary) with colour dots and an Edit button.
 * Long summaries in several rows must not squeeze the Name column, move the dots and Edit button onto a second
 * line, or change a column's width.
 */
export const LongText: Story = {
  render: () => (
    <TextStress
      render={(long) => (
        <DefinitionList<Summarised>
          layout="grid"
          items={[
            { id: "a", name: stressText(long, "Software"), summary: stressText(long, "Software · Solid, one-way", "summary") },
            { id: "b", name: "Power", summary: stressText(long, "Electrical · Dashed", "summary") },
            { id: "c", name: stressText(long, "Data", "word"), summary: stressText(long, "Data", "word") },
          ]}
          fields={[{ key: "name", getValue: (i) => i.name, label: "Name", ariaLabel: "Type name" }]}
          getReassignLabel={(i) => i.name}
          onRename={async () => {}}
          onAdd={async () => {}}
          onDelete={async () => {}}
          deleteLabel="Delete type"
          addLabel="Add type"
          renderExtra={(item) => (
            <span className="row" style={{ gap: "var(--space-3)", alignItems: "center" }}>
              <CellText className="text-muted">{item.summary}</CellText>
              <span aria-hidden="true">●●</span>
              <button className="btn" aria-label={`Edit ${item.name.slice(0, 12)}`}>Edit</button>
            </span>
          )}
        />
      )}
    />
  ),
  play: async ({ canvasElement }) => {
    await expectStressStable(canvasElement);
  },
};

/** A list whose Add button hands the create form to its caller, with one extra row in the list's actions menu. */
function CallerOwnedAddHarness() {
  const [open, setOpen] = useState(false);
  const [restored, setRestored] = useState(false);
  return (
    <>
      <DefinitionList<Named>
        items={[{ id: "1", name: "Bug" }]}
        fields={[{ key: "name", getValue: (i) => i.name, placeholder: "Name" }]}
        getReassignLabel={(i) => i.name}
        onRename={fn(async () => {})}
        onAddRequest={() => setOpen(true)}
        onDelete={fn(async () => {})}
        deleteLabel="Delete type"
        addLabel="Add type"
        menuItems={[{ key: "restore", label: "Add organisation defaults (1)", onSelect: () => setRestored(true) }]}
      />
      {open && <div role="dialog" aria-label="Caller's own form">Full form</div>}
      {restored && <p>Restored</p>}
    </>
  );
}

/** A list whose caller owns the create form: the one Add button calls `onAddRequest` instead of opening the name dialog, and the list's other actions are rows of one menu beside it. */
export const AddRequestOpensTheCallersOwnDialog: Story = {
  render: () => <CallerOwnedAddHarness />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "List actions" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Add organisation defaults (1)" }));
    await expect(await canvas.findByText("Restored")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Add type" }));
    await expect(await canvas.findByRole("dialog", { name: "Caller's own form" })).toBeInTheDocument();
    // The list's own name dialog did not open.
    await expect(screen.queryByRole("dialog", { name: "Add type" })).not.toBeInTheDocument();
  },
};
