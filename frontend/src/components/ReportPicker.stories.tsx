import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, screen, userEvent, within } from "storybook/test";

import { buildUser, withStatefulAuth } from "../testing/storybook-helpers";
import { ReportPicker, type ReportPickerItem } from "./ReportPicker";

const items: ReportPickerItem[] = [
  { id: "requirements", title: "Requirements report", description: "The project's requirements.", folder: "Platform", kind: "report", favouriteKey: "report:platform.requirements" },
  { id: "decision-register", title: "Decision register", description: "Every Decision.", folder: "Decision Management", kind: "report", favouriteKey: "report:decisions.d1" },
  { id: "risk-register", title: "Risk register", description: "Every Risk.", folder: "Risk Management", kind: "report", favouriteKey: "report:risk_management.r1" },
  { id: "handover", title: "Handover document", description: "For the external team.", folder: "Handover/Quarterly", kind: "report", favouriteKey: "layout:1" },
  { id: "handover-rows", title: "Handover rows", description: "One row per requirement.", folder: "Handover/Quarterly", kind: "sheet", favouriteKey: "layout:2" },
  { id: "pack-1", title: "Programme handover", description: "A zip of the handover reports.", folder: "Handover", kind: "pack", favouriteKey: "pack:1" },
];

/** Hosts the picker with a selection it can change, so a story sees the button follow the choice. */
function Host({ initial = "requirements" }: { initial?: string }) {
  const [selected, setSelected] = useState(initial);
  return <ReportPicker pickerId="story" items={items} selectedId={selected} onSelect={setSelected} />;
}

/**
 * The Reports page's chooser: a button for the current report that opens a dialog with search, a type filter, a
 * Favourites folder and the reports in nested folders.
 */
const meta: Meta<typeof ReportPicker> = {
  title: "Components/Reports/ReportPicker",
  component: ReportPicker,
  decorators: [withStatefulAuth(buildUser({ ui_preferences: {} }))],
  render: () => <Host />,
};
export default meta;

type Story = StoryObj<typeof ReportPicker>;

const dialog = async () => within(await screen.findByRole("dialog", { name: "Choose a report" }));

/** The button names the current report and the folder it is filed in. */
export const ShowsTheCurrentReportAndItsFolder: Story = {
  play: async ({ canvasElement }) => {
    const button = within(canvasElement).getByRole("button", { name: "Report: Requirements report" });
    await expect(button).toHaveTextContent("Platform");
    await expect(within(canvasElement).getByText("The project's requirements.")).toBeInTheDocument();
  },
};

/** The first time a picker opens, every folder is collapsed, the selection's included. */
export const OpensFullyCollapsedTheFirstTime: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Report: Requirements report" }));
    const d = await dialog();
    await expect(d.getByRole("button", { name: "Expand Platform" })).toBeInTheDocument();
    await expect(d.getByRole("button", { name: "Expand Risk Management" })).toBeInTheDocument();
    await expect(d.queryByRole("button", { name: /^Risk register/ })).not.toBeInTheDocument();
    await userEvent.click(d.getByRole("button", { name: "Expand Risk Management" }));
    await expect(d.getByRole("button", { name: /^Risk register/ })).toBeInTheDocument();
  },
};

/** Closing and reopening shows the same folders open, and a different picker keeps its own folders. */
export const RemembersTheOpenFolders: Story = {
  play: async ({ canvasElement }) => {
    const open = () => userEvent.click(within(canvasElement).getByRole("button", { name: /^Report:/ }));
    await open();
    let d = await dialog();
    await userEvent.click(d.getByRole("button", { name: "Expand Risk Management" }));
    await userEvent.click(d.getByRole("button", { name: "Expand Handover" }));
    await userEvent.click(d.getByRole("button", { name: "Collapse Handover" }));
    await userEvent.keyboard("{Escape}");
    await open();
    d = await dialog();
    await expect(d.getByRole("button", { name: "Collapse Risk Management" })).toBeInTheDocument();
    await expect(d.getByRole("button", { name: "Expand Handover" })).toBeInTheDocument();
    await expect(d.getByRole("button", { name: "Expand Platform" })).toBeInTheDocument();
  },
};

/** Searching opens the folders for the match but does not overwrite what was open: clearing the search restores it. */
export const SearchDoesNotChangeTheSavedFolders: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: /^Report:/ }));
    const d = await dialog();
    await userEvent.type(d.getByRole("textbox", { name: "Search reports" }), "register");
    await expect(d.getByRole("button", { name: /^Risk register/ })).toBeInTheDocument();
    await userEvent.clear(d.getByRole("textbox", { name: "Search reports" }));
    await expect(d.getByRole("button", { name: "Expand Risk Management" })).toBeInTheDocument();
  },
};

/** The favourite star is the last control of the row, after the report's button. */
export const StarIsOnTheRightOfTheRow: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: /^Report:/ }));
    const d = await dialog();
    await userEvent.click(d.getByRole("button", { name: "Expand Risk Management" }));
    const star = d.getByRole("button", { name: "Add Risk register to favourites" });
    const report = d.getByRole("button", { name: /^Risk register/ });
    await expect(report.compareDocumentPosition(star) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    await expect(star.nextElementSibling).toBeNull();
  },
};

/** Folders nest: Handover holds the pack and a Quarterly folder. */
export const NestsFolders: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Report: Requirements report" }));
    const d = await dialog();
    await userEvent.click(d.getByRole("button", { name: "Expand Handover" }));
    await expect(d.getByRole("button", { name: /^Programme handover/ })).toBeInTheDocument();
    await userEvent.click(d.getByRole("button", { name: "Expand Quarterly" }));
    await expect(d.getByRole("button", { name: /^Handover document/ })).toBeInTheDocument();
  },
};

/** Searching opens every folder that still holds a match and hides the rest. */
export const SearchOpensMatchingFolders: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Report: Requirements report" }));
    const d = await dialog();
    await userEvent.type(d.getByRole("textbox", { name: "Search reports" }), "register");
    await expect(d.getByRole("button", { name: /^Decision register/ })).toBeInTheDocument();
    await expect(d.getByRole("button", { name: /^Risk register/ })).toBeInTheDocument();
    await expect(d.queryByRole("button", { name: /^Handover document/ })).not.toBeInTheDocument();
    await userEvent.clear(d.getByRole("textbox", { name: "Search reports" }));
    await userEvent.type(d.getByRole("textbox", { name: "Search reports" }), "zzz");
    await expect(d.getByText("No reports match.")).toBeInTheDocument();
  },
};

/** The type filter narrows to reports, sheets or packs. */
export const FiltersByKind: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Report: Requirements report" }));
    const d = await dialog();
    await userEvent.selectOptions(d.getByLabelText("Show"), "Sheets");
    await expect(d.getByRole("button", { name: /^Handover rows/ })).toBeInTheDocument();
    await expect(d.queryByRole("button", { name: /^Risk register/ })).not.toBeInTheDocument();
    await userEvent.selectOptions(d.getByLabelText("Show"), "Packs");
    await expect(d.getByRole("button", { name: /^Programme handover/ })).toBeInTheDocument();
    await expect(d.queryByRole("button", { name: /^Handover rows/ })).not.toBeInTheDocument();
  },
};

/** A starred report also appears in the Favourites folder, which is first and, like any folder, opens when asked; unstarring removes it. */
export const FavouritesAreListedFirst: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Report: Requirements report" }));
    let d = await dialog();
    await expect(d.queryByRole("button", { name: /Favourites$/ })).not.toBeInTheDocument();
    await userEvent.click(d.getByRole("button", { name: "Expand Risk Management" }));
    await userEvent.click(d.getByRole("button", { name: "Add Risk register to favourites" }));
    d = await dialog();
    await userEvent.click(d.getByRole("button", { name: "Expand Favourites" }));
    await expect(d.getByRole("button", { name: "Collapse Favourites" })).toBeInTheDocument();
    await expect(d.getAllByRole("button", { name: /^Risk register/ }).length).toBeGreaterThan(1);
    await userEvent.click(d.getAllByRole("button", { name: "Remove Risk register from favourites" })[0]);
    await expect((await dialog()).queryByRole("button", { name: /Favourites$/ })).not.toBeInTheDocument();
  },
};

/** Choosing a report closes the dialog and the button names it. */
export const ChoosingAReportClosesTheDialog: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Report: Requirements report" }));
    const d = await dialog();
    await userEvent.click(d.getByRole("button", { name: "Expand Decision Management" }));
    await userEvent.click(d.getByRole("button", { name: /^Decision register/ }));
    await expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await expect(within(canvasElement).getByRole("button", { name: "Report: Decision register" })).toBeInTheDocument();
  },
};

/** Each report carries a type icon named for what it is, and the list is a file-manager style grid of folders and reports. */
export const ReportsAreAListWithTypeIcons: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Report: Requirements report" }));
    const d = await dialog();
    await expect(d.getByRole("treegrid", { name: "Reports" })).toBeInTheDocument();
    await userEvent.click(d.getByRole("button", { name: "Expand Handover" }));
    await expect(d.getByRole("img", { name: "Pack" })).toBeInTheDocument();
    await userEvent.click(d.getByRole("button", { name: "Expand Quarterly" }));
    await expect(d.getByRole("img", { name: "Sheet" })).toBeInTheDocument();
    await expect(d.getByRole("img", { name: "Report" })).toBeInTheDocument();
  },
};

/** Reversing the Name sort keeps Favourites on top and folders before reports. */
export const FavouritesStayFirstWhenSorted: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Report: Requirements report" }));
    const d = await dialog();
    await userEvent.click(d.getByRole("button", { name: "Expand Risk Management" }));
    await userEvent.click(d.getByRole("button", { name: "Add Risk register to favourites" }));
    const grid = (await dialog()).getByRole("treegrid", { name: "Reports" });
    await userEvent.click(within(grid).getByRole("button", { name: "Name" }));
    await expect(within(grid).getAllByRole("row")[1]).toHaveTextContent("Favourites");
  },
};

/** Arrow keys walk the report list and Enter chooses the focused report. */
export const KeyboardChoosesAReport: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Report: Requirements report" }));
    const d = await dialog();
    await userEvent.click(d.getByRole("button", { name: "Expand Decision Management" }));
    const row = d.getByRole("button", { name: /^Decision register/ }).closest<HTMLElement>("[role=row]")!;
    row.focus();
    await userEvent.keyboard("{Enter}");
    await expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await expect(within(canvasElement).getByRole("button", { name: "Report: Decision register" })).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...ShowsTheCurrentReportAndItsFolder, globals: { theme: "light" } };
export const DarkTheme: Story = { ...ShowsTheCurrentReportAndItsFolder, globals: { theme: "dark" } };
