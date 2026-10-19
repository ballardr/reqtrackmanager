import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildCandidate, buildOption } from "../../testing/artefactLinksFixtures";

import { PainPointFormModal } from "./PainPointFormModal";
import type { EffectivePainPointType, PainPoint } from "./types";

const TYPES: EffectivePainPointType[] = [
  { id: "type-market", name: "Market", display_order: 0, is_enabled: true, source: "org" },
  { id: "type-user", name: "User", display_order: 1, is_enabled: true, source: "org" },
  { id: "type-operator", name: "Operator", display_order: 2, is_enabled: true, source: "org" },
];

/**
 * `PainPointFormModal` renders via `Modal`, which portals to `document.body`
 * — every assertion here queries `within(document.body)`, mirroring
 * `StrategyFormModal.stories.tsx`'s own identical convention.
 */
const meta: Meta<typeof PainPointFormModal> = {
  title: "Modules/ContextStrategy/PainPointFormModal",
  component: PainPointFormModal,
  args: { types: TYPES, onCancel: fn(), onSave: fn() },
};
export default meta;

type Story = StoryObj<typeof PainPointFormModal>;

export const CreateNew: Story = {
  play: async () => {
    const body = within(document.body);
    await expect(body.getByRole("heading", { name: "New Pain Point" })).toBeInTheDocument();
  },
};

export const SubmitsNewPainPoint: Story = {
  play: async ({ args }) => {
    const body = within(document.body);
    await userEvent.selectOptions(body.getByLabelText("Type"), "type-operator");
    await userEvent.type(body.getByLabelText("Pain Point title"), "Field reports require paper re-keying");
    await userEvent.type(body.getByLabelText("Description"), "Operators re-key paper forms into the system by hand.");
    await userEvent.click(body.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(args.onSave).toHaveBeenCalledWith(
      expect.objectContaining({ pain_point_type_id: "type-operator", title: "Field reports require paper re-keying" }), []
    ));
  },
};

/** The intentional-limitation switch defaults off and is saved when flipped. */
export const MarksAnIntentionalLimitation: Story = {
  play: async ({ args }) => {
    const body = within(document.body);
    const toggle = body.getByRole("switch", { name: "Intentional limitation" });
    await expect(toggle).toHaveAttribute("aria-checked", "false");
    await userEvent.selectOptions(body.getByLabelText("Type"), "type-market");
    await userEvent.type(body.getByLabelText("Pain Point title"), "Export limited to 100 rows on Standard");
    await userEvent.click(toggle);
    await userEvent.click(body.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.onSave).toHaveBeenCalledWith(expect.objectContaining({ is_intentional: true }), []));
  },
};

export const SaveDisabledUntilRequiredFieldsFilled: Story = {
  play: async () => {
    const body = within(document.body);
    await expect(body.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.selectOptions(body.getByLabelText("Type"), "type-market");
    await expect(body.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.type(body.getByLabelText("Pain Point title"), "Competitive pricing pressure");
    await expect(body.getByRole("button", { name: "Save" })).toBeEnabled();
  },
};

export const EditExistingOffersDisabledCurrentType: Story = {
  args: {
    types: [{ id: "type-legacy", name: "Legacy", display_order: 3, is_enabled: false, source: "org" }, ...TYPES],
    initial: {
      id: "pain-point-1", project_id: "project-1", unique_code: "PP-001", pain_point_type_id: "type-legacy", pain_point_type_name: "Legacy",
      creator_id: "user-1", is_archived: false, archived_at: null, archived_by: null,
      title: "Report delays under poor connectivity", description: "Field reports queue for days.",
      source: "Operator interviews", impact: "Decisions are made on stale data.", evidence: "12 reports last month.",
      priority: "high", status: "submitted", owner: null, date_identified: "2026-01-05", is_intentional: false, is_locked: false,
      created_at: "2026-01-05T09:00:00Z", updated_at: "2026-01-05T09:00:00Z",
    } satisfies PainPoint,
  },
  play: async () => {
    const body = within(document.body);
    await expect(body.getByRole("heading", { name: "Edit Report delays under poor connectivity" })).toBeInTheDocument();
    await expect(body.getByDisplayValue("Field reports queue for days.")).toBeInTheDocument();
    // The Pain Point's own current type still appears even though it is now disabled.
    await expect(within(body.getByLabelText("Type")).getByRole("option", { name: "Legacy (disabled)" })).toBeInTheDocument();
  },
};

/** Worst case: a long save error and a long unbroken title. The error is shown, and the dialog neither scrolls
 * sideways nor pushes Save out of reach. */
export const LongErrorAndLongTitleKeepTheActionsReachable: Story = {
  args: { error: "Could not save: " + "the server rejected this request for a reason that takes a while to explain. ".repeat(4) },
  play: async () => {
    const body = within(document.body);
    await userEvent.type(body.getByLabelText("Pain Point title"), "W".repeat(200));
    await expect(body.getByText(/Could not save:/)).toBeVisible();
    await expect(body.getByRole("button", { name: "Save" })).toBeVisible();
    const dialog = body.getByRole("dialog");
    await expect(dialog.scrollWidth).toBeLessThanOrEqual(dialog.clientWidth + 1);
  },
};

export const LightTheme: Story = { ...CreateNew };
export const DarkTheme: Story = { ...CreateNew, globals: { theme: "dark" } };

/** Reads the quick-link field makes about a Pain Point that does not exist yet: the usable link types and the personas to offer. */
function mockLinkFinder() {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.includes("/link-candidates")) {
      return {
        items: [buildCandidate({ type: "persona", id: "per-1", type_label: "Persona", label: "PER-001 Field engineer" })],
        truncated: false,
      };
    }
    if (path.includes("/link-types")) return [buildOption({ other_types: [{ type: "persona", label: "Persona" }] })];
    throw new Error(`unmocked path: ${path}`);
  });
}

/** A create form opened with its project offers "Link to", listing personas first, and hands the chosen records to `onSave`. */
export const LinksToAPersonaOnCreate: Story = {
  args: { projectId: "project-1" },
  beforeEach: mockLinkFinder,
  play: async ({ args }) => {
    const body = within(document.body);
    await userEvent.selectOptions(body.getByLabelText("Type"), "type-operator");
    await userEvent.type(body.getByLabelText("Pain Point title"), "Field reports require paper re-keying");
    await userEvent.click(await body.findByRole("combobox", { name: "Link to" }));
    await userEvent.click(await body.findByRole("option", { name: /PER-001 Field engineer/ }));
    await userEvent.click(body.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.onSave).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Field reports require paper re-keying" }),
      [expect.objectContaining({ other_type: "persona", other_id: "per-1", link_type_id: "lt-related" })],
    ));
  },
};

/** An existing record's links live in its Links panel, so the edit form never offers the field. */
export const EditDoesNotOfferTheQuickLinkField: Story = {
  args: {
    projectId: "project-1",
    initial: {
      id: "pp-1", project_id: "project-1", pain_point_type_id: "type-operator", title: "Slow reports", priority: "medium",
    } as PainPoint,
  },
  beforeEach: mockLinkFinder,
  play: async () => {
    await expect(within(document.body).queryByRole("combobox", { name: "Link to" })).not.toBeInTheDocument();
  },
};
