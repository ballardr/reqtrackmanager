import type { Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter } from "react-router-dom";
import { expect, fn, userEvent, within } from "storybook/test";

import { Badge } from "./Badge";
import { RecordHeader } from "./RecordHeader";
import { ReturnLink } from "./ReturnLink";
import { orphanedControlViolations } from "../testing/orphanedControls";
import { STRESS_TEXT, expectStressStable, stressText } from "../testing/stressFixtures";
import { TextStress } from "../testing/TextStress";

/**
 * Asserts the code follows the title: on the title's last line after its last word, or on the line below it. Never beside
 * the actions on the first line of a title that wraps.
 */
async function expectCodeFollowsTitle(canvasElement: HTMLElement, code: string) {
  const heading = canvasElement.querySelector<HTMLElement>(".record-header__heading")!;
  const codeEl = within(canvasElement).getByText(code, { exact: false }).closest<HTMLElement>(".record-header__code")!;
  const range = document.createRange();
  range.selectNodeContents(heading);
  const lines = Array.from(range.getClientRects());
  const last = lines[lines.length - 1];
  const c = codeEl.getBoundingClientRect();
  const afterLastWord = c.top < last.bottom && c.bottom > last.top && c.left >= last.right - 1;
  const onTheNextLine = c.top >= last.bottom - 1;
  await expect(afterLastWord || onTheNextLine, `code at ${c.left},${c.top}; title ends ${last.right},${last.bottom}`).toBe(true);
  const row = canvasElement.querySelector<HTMLElement>(".item-row")!;
  await expect(row.scrollWidth).toBeLessThanOrEqual(row.clientWidth + 1);
}

const meta: Meta<typeof RecordHeader> = {
  title: "Components/RecordHeader",
  component: RecordHeader,
  decorators: [(Story) => <MemoryRouter><div style={{ maxWidth: 720 }}><Story /></div></MemoryRouter>],
  args: {
    recordLabel: "Persona",
    title: "Ada Lovelace",
    code: "PER-001",
    subtitle: "Analyst",
    version: 3,
    back: { to: "/personas", label: "Personas" },
    badges: <><Badge>Project</Badge><Badge tone="accent">Active</Badge></>,
    onEdit: fn(),
    transitions: <button className="btn btn-danger">Retire</button>,
    actions: [{ label: "Archive", danger: true, onSelect: fn() }],
  },
};
export default meta;
type Story = StoryObj<typeof RecordHeader>;

/** Edit is a visible pencil; everything else sits behind the "{Record} actions" menu. */
export const Default: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Edit" }));
    await expect(args.onEdit).toHaveBeenCalled();
    await expect(canvas.getByRole("button", { name: "Retire" })).toBeInTheDocument();
    // The header draws the back arrow; the page passes only the list's plural name.
    await expect(canvas.getByRole("link", { name: "← Personas" })).toHaveAttribute("href", "/personas");
    await userEvent.click(canvas.getByRole("button", { name: "Persona actions" }));
    await expect(within(document.body).getByRole("menuitem", { name: "Archive" })).toBeInTheDocument();
  },
};

/** The version is a labelled, muted item on the badge line, never a line of its own. */
export const VersionAfterTheBadges: Story = {
  play: async ({ canvasElement }) => {
    const version = within(canvasElement).getByText("Version 3");
    await expect(version).toHaveAttribute("title", "Version 3 of this record");
    await expect(version.parentElement).toContainElement(within(canvasElement).getByText("Active"));
  },
};

/** A version with no badges still sits on its own badge line; a record with no version shows none. */
export const VersionOnly: Story = {
  args: { badges: undefined, subtitle: undefined },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("Version 3")).toBeInTheDocument();
  },
};

export const NoVersionNoSubtitle: Story = {
  args: { version: undefined, subtitle: undefined, badges: undefined },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByText(/Version/)).not.toBeInTheDocument();
  },
};

/** A long title keeps the version on the badge line under it. */
export const LongTitleWithVersion: Story = {
  args: { title: "A very long persona name that would otherwise push everything around when it wraps across several lines" },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("Version 3")).toBeInTheDocument();
  },
};

/** A record the organisation owns is qualified with the organisation's code. */
export const CodeOwnedByTheOrganisation: Story = {
  args: { codeOwner: "ACME" },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("ACME-PER-001")).toBeInTheDocument();
  },
};

/** A single object action still gets the menu, so its position never depends on permissions. */
export const SingleActionStillUsesTheMenu: Story = {
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("button", { name: "Persona actions" })).toBeInTheDocument();
  },
};

/** No permissions: no Edit, no menu, no empty kebab. */
export const NoPermissions: Story = {
  args: { onEdit: undefined, actions: [false, null], transitions: undefined },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Persona actions" })).not.toBeInTheDocument();
  },
};

/** A very long title wraps inside its own box; Edit and the menu stay on the title row, and the code follows the title's last word. */
export const LongTitle: Story = {
  args: { title: "An exceptionally long record title ".repeat(8) },
  play: async ({ canvasElement }) => {
    await expect(orphanedControlViolations(canvasElement)).toEqual([]);
    await expectCodeFollowsTitle(canvasElement, "PER-001");
  },
};

/** A long unbroken title breaks inside its box; the code stays after it. */
export const LongUnbrokenTitle: Story = {
  args: { title: STRESS_TEXT.word.repeat(3) },
  play: async ({ canvasElement }) => {
    await expect(orphanedControlViolations(canvasElement)).toEqual([]);
    await expectCodeFollowsTitle(canvasElement, "PER-001");
  },
};

/** A title with no actions still carries the code after its last word. */
export const LongTitleWithoutActions: Story = {
  args: { title: "An exceptionally long record title ".repeat(8), onEdit: undefined, actions: [], transitions: undefined },
  play: async ({ canvasElement }) => {
    await expectCodeFollowsTitle(canvasElement, "PER-001");
  },
};

/** A long project-qualified code stays whole and inside the row, after a long title. */
export const LongCodeWithLongTitle: Story = {
  args: { title: "An exceptionally long record title ".repeat(4), code: "REQ-000123", codeOwner: "ACME-ENGINEERING-PLATFORM" },
  play: async ({ canvasElement }) => {
    await expectCodeFollowsTitle(canvasElement, "ACME-ENGINEERING-PLATFORM-REQ-000123");
  },
};

/** The code and a title switcher flow after the title, in that order. */
export const LongTitleWithSwitcher: Story = {
  args: { title: "An exceptionally long record title ".repeat(4), titleAddon: <button className="btn btn-icon" aria-label="Switch record">⇅</button> },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expectCodeFollowsTitle(canvasElement, "PER-001");
    await expect(canvas.getByText("PER-001").compareDocumentPosition(canvas.getByRole("button", { name: "Switch record" })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  },
};

/** A phone-width column: the title wraps over several lines and the code still follows it. */
export const LongTitleNarrow: Story = {
  args: { title: "An exceptionally long record title ".repeat(4) },
  decorators: [(Story) => <div style={{ maxWidth: 320 }}><Story /></div>],
  play: async ({ canvasElement }) => {
    await expect(orphanedControlViolations(canvasElement)).toEqual([]);
    await expectCodeFollowsTitle(canvasElement, "PER-001");
  },
};

export const LongTitleDark: Story = { ...LongTitle, globals: { theme: "dark" } };

/** Short and long text at the same width: the actions keep their place and nothing leaves the row. */
export const LongText: Story = {
  render: (args) => (
    <TextStress
      width={640}
      render={(long) => (
        <RecordHeader {...args} title={stressText(long, "Ada Lovelace")} code={long ? STRESS_TEXT.code : "PER-001"} />
      )}
    />
  ),
  play: async ({ canvasElement }) => {
    await expectStressStable(canvasElement);
  },
};

export const ManyBadges: Story = {
  args: {
    badges: (
      <>
        {["Project", "Active", "Review overdue", "Archived", "Retention review due"].map((b) => <Badge key={b}>{b}</Badge>)}
      </>
    ),
  },
};

export const DarkTheme: Story = { globals: { theme: "dark" } };

/** Tags, components and references sit on the line under the title, after the badges and the version. */
export const TagsAfterTheBadgesAndVersion: Story = {
  args: { tags: <span>Safety</span> },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const line = canvas.getByText("Version 3").parentElement!;
    await expect(line).toContainElement(canvas.getByText("Safety"));
    await expect(line).toContainElement(canvas.getByText("Active"));
    await expect(canvas.getByText("Version 3").compareDocumentPosition(canvas.getByText("Safety")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  },
};

/** A record with no badges and no version still gets the line for its tags. */
export const TagsWithNoBadgesOrVersion: Story = {
  args: { tags: <span>Safety</span>, badges: undefined, version: undefined },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("Safety").closest(".record-header__line")).not.toBeNull();
  },
};

/** A `tags` element that draws nothing (a record with none that the viewer cannot add to) and no badges leave no line and no gap. */
export const EmptyTagsLeaveNoLine: Story = {
  args: { tags: <></>, badges: undefined, version: undefined },
  play: async ({ canvasElement }) => {
    const line = canvasElement.querySelector<HTMLElement>(".record-header__line")!;
    await expect(getComputedStyle(line).display).toBe("none");
  },
};

/** A `stateMenu` sits beside Edit in the title row, before it, and counts as a control by itself. */
export const StateMenuBesideEdit: Story = {
  args: { stateMenu: <button className="btn">Change status</button> },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const state = canvas.getByRole("button", { name: "Change status" });
    const edit = canvas.getByRole("button", { name: "Edit" });
    await expect(state.parentElement).toBe(edit.parentElement);
    await expect(state.compareDocumentPosition(edit) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  },
};

/** A return control sits on the back link's line, after it, and leads to where the person came from. */
export const ReturnLinkBesideTheBackLink: Story = {
  args: { returnTo: <ReturnLink to="/diagrams/dgm-1" label="DGM-001 Main system" /> },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const back = canvas.getByRole("link", { name: "← Personas" });
    const returning = canvas.getByRole("link", { name: "Return to DGM-001 Main system" });
    await expect(returning).toHaveAttribute("href", "/diagrams/dgm-1");
    await expect(back.parentElement).toBe(returning.parentElement);
    await expect(back.compareDocumentPosition(returning) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  },
};
