import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { buildLinkType, buildRequirement, withTerminology } from "../testing/storybook-helpers";
import { RequirementLinkPickerModal } from "./RequirementLinkPickerModal";

/**
 * The shared "Add link" picker (`pages/RequirementDetailPage.tsx`,
 * platform-review-2026-09 Phase 7) — always offers built-in Search and
 * Requirements tabs; any currently-enabled module can contribute further
 * tabs (`extraTabs`, computed by the caller from `requirementLinkPickerTabs`
 * — see `RequirementDetailPage.stories.tsx`'s `LinksCardWithCompliance
 * LinkPickerTab` for that integration). Mounted directly here since this
 * component has no fetches of its own — everything arrives as props.
 */
const meta: Meta<typeof RequirementLinkPickerModal> = {
  title: "Components/RequirementLinkPickerModal",
  component: RequirementLinkPickerModal,
  decorators: [withTerminology()],
};
export default meta;

type Story = StoryObj<typeof RequirementLinkPickerModal>;

const targets = [
  buildRequirement({ id: "req-2", unique_code: "AUTH-LOG-002", name: "Users can enable two-factor authentication", component_id: "comp-1", category_id: "cat-1" }),
  buildRequirement({ id: "req-3", unique_code: "AUTH-LOG-003", name: "Passwords expire after 90 days", component_id: "comp-1", category_id: "cat-1" }),
];
const components = [
  { id: "comp-1", project_id: "project-1", name: "Authentication", prefix: "AUTH", sort_order: 0 },
  { id: "comp-2", project_id: "project-1", name: "Infrastructure", prefix: "INFRA", sort_order: 1 },
];
const categories = [{ id: "cat-1", project_id: "project-1", component_id: "comp-1", name: "Login", prefix: "LOG", sort_order: 0 }];
const linkTypes = [buildLinkType({ id: "lt-1", forward_name: "Depends on", reverse_name: "Is a dependency of" })];

export const SearchTabFiltersByCodeOrName: Story = {
  args: {
    eligibleTargets: targets,
    components,
    categories,
    linkTypes,
    extraTabs: [],
    linksLocked: false,
    onAddCoreLink: fn(async () => {}),
    onClose: fn(),
  },
  play: async ({ args }) => {
    const body = within(document.body);
    // Search is the default-active tab.
    await expect(body.getByLabelText("Target requirement")).toBeInTheDocument();
    await expect(body.getByRole("option", { name: "AUTH-LOG-002 — Users can enable two-factor authentication" })).toBeInTheDocument();
    await expect(body.getByRole("option", { name: "AUTH-LOG-003 — Passwords expire after 90 days" })).toBeInTheDocument();

    await userEvent.type(body.getByPlaceholderText("Search by code or name…"), "90 days");
    await expect(body.queryByRole("option", { name: "AUTH-LOG-002 — Users can enable two-factor authentication" })).not.toBeInTheDocument();
    await expect(body.getByRole("option", { name: "AUTH-LOG-003 — Passwords expire after 90 days" })).toBeInTheDocument();

    await userEvent.selectOptions(body.getByLabelText("Target requirement"), "req-3");
    await userEvent.selectOptions(body.getByLabelText("Link type"), "lt-1");
    await userEvent.click(body.getByRole("button", { name: "Add link" }));
    await waitFor(() => expect(args.onAddCoreLink).toHaveBeenCalledWith("req-3", "lt-1", undefined));
  },
};

export const RequirementsTabCascades: Story = {
  args: {
    eligibleTargets: targets,
    components,
    categories,
    linkTypes,
    extraTabs: [],
    linksLocked: false,
    onAddCoreLink: fn(async () => {}),
    onClose: fn(),
  },
  play: async ({ args }) => {
    const body = within(document.body);
    await userEvent.click(body.getByRole("tab", { name: "Requirements" }));
    // The target select is empty until a component is chosen — component
    // and category form a genuine two-level tree, not two independent
    // filters (`ProjectCategory.component_id`).
    await expect(body.getByLabelText("Target requirement")).toBeDisabled();

    await userEvent.selectOptions(body.getByLabelText("Component"), "comp-1");
    // comp-1 has exactly one category — it's auto-selected rather than left
    // for the user to pick from a dropdown with only one real option.
    await expect(body.getByLabelText("Category")).toHaveValue("cat-1");
    await expect(body.getByLabelText("Target requirement")).toBeEnabled();

    // comp-2 has zero categories — the placeholder correctly reports that,
    // rather than the earlier bug where it said "no categories" for any
    // component whenever none was selected yet, even one that does have some.
    await userEvent.selectOptions(body.getByLabelText("Component"), "comp-2");
    await expect(body.getByLabelText("Category")).toHaveValue("");
    await expect(within(body.getByLabelText("Category")).getByRole("option", { name: /no categories/i })).toBeInTheDocument();

    await userEvent.selectOptions(body.getByLabelText("Component"), "comp-1");
    await userEvent.selectOptions(body.getByLabelText("Target requirement"), "req-2");
    await userEvent.selectOptions(body.getByLabelText("Link type"), "lt-1");
    await userEvent.click(body.getByRole("button", { name: "Add link" }));
    await waitFor(() => expect(args.onAddCoreLink).toHaveBeenCalledWith("req-2", "lt-1", undefined));
  },
};

/** Platform review 2026-09, Phase 8 — once the target requirement is
 * approved and the project/org requires a change request for link
 * changes, both built-in tabs grow a "Reason for change" field and Add
 * stays disabled until it's filled; the caller then submits an `add_link`
 * change request with that reason instead of calling the direct endpoint. */
export const LinksLockedRequiresReason: Story = {
  args: {
    eligibleTargets: targets,
    components,
    categories,
    linkTypes,
    extraTabs: [],
    linksLocked: true,
    onAddCoreLink: fn(async () => {}),
    onClose: fn(),
  },
  play: async ({ args }) => {
    const body = within(document.body);
    await expect(body.getByText(/requires a change request/i)).toBeInTheDocument();
    await userEvent.selectOptions(body.getByLabelText("Target requirement"), "req-3");
    await userEvent.selectOptions(body.getByLabelText("Link type"), "lt-1");
    const addButton = body.getByRole("button", { name: "Add link" });
    await expect(addButton).toBeDisabled();

    await userEvent.type(body.getByLabelText("Reason for change"), "Scope correction agreed with the customer.");
    await expect(addButton).toBeEnabled();
    await userEvent.click(addButton);
    await waitFor(() =>
      expect(args.onAddCoreLink).toHaveBeenCalledWith("req-3", "lt-1", "Scope correction agreed with the customer.")
    );
  },
};

export const ContributedTabAppearsAlongsideBuiltIns: Story = {
  args: {
    eligibleTargets: [],
    components: [],
    categories: [],
    linkTypes: [],
    extraTabs: [{ key: "compliance-requirements", label: "Compliance", node: <p>Compliance module content.</p> }],
    linksLocked: false,
    onAddCoreLink: fn(async () => {}),
    onClose: fn(),
  },
  play: async () => {
    const body = within(document.body);
    await expect(body.getByRole("tab", { name: "Search" })).toBeInTheDocument();
    await expect(body.getByRole("tab", { name: "Requirements" })).toBeInTheDocument();
    await expect(body.getByRole("tab", { name: "Compliance" })).toBeInTheDocument();
    // Every tab panel — built-in and contributed alike — is conditionally
    // rendered, only the active one mounted: a contributed tab reuses core
    // labels like "Link type"/"Add link" (the same core `RequirementLink
    // TypeDefinition` vocabulary), and an always-mounted-but-hidden inactive
    // panel would leave a second, hidden element with that same accessible
    // name in the DOM — an ambiguous match for any `getByLabel`/`getByText`
    // query made while a different tab is active.
    await expect(body.queryByText("Compliance module content.")).not.toBeInTheDocument();

    await userEvent.click(body.getByRole("tab", { name: "Compliance" }));
    await expect(body.getByText("Compliance module content.")).toBeVisible();
  },
};
