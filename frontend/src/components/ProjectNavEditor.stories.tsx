import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { ProjectListItem, UiPreferenceValue, User } from "../api/types";
import { AuthContext } from "../context/AuthContextValue";
import { applyUiPreferencePatch } from "../context/uiPreferencePatch";
import { buildProjectNavItems, NAV_PROJECT_ID } from "../testing/projectNavFixtures";
import { buildUser, withToast } from "../testing/storybook-helpers";
import { ProjectNavEditor } from "./ProjectNavEditor";

/**
 * Auth provider that records every `setUiPreferences` call (the editor's single write) while
 * still applying it, so a story can assert both the exact patch and the resulting preferences.
 */
function RecordingAuth({ user, onWrite, rejectWith, children }: {
  user: User;
  onWrite: (patch: Record<string, UiPreferenceValue | null>) => void;
  /** When set, the write is recorded but rejected with this error (as the server does for a 422). */
  rejectWith?: Error;
  children: React.ReactNode;
}) {
  const [current, setCurrent] = useState(user);
  return (
    <AuthContext.Provider
      value={{
        user: current,
        loading: false,
        login: async () => { throw new Error("not mocked"); },
        signup: async () => { throw new Error("not mocked"); },
        verify2fa: async () => { throw new Error("not mocked"); },
        logout: () => {},
        refreshUser: async () => {},
        setUiPreference: () => {},
        setUiPreferences: async (patch) => {
          onWrite(patch);
          if (rejectWith) throw rejectWith;
          setCurrent((u) => ({ ...u, ui_preferences: applyUiPreferencePatch(u.ui_preferences, patch) }));
        },
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

const onWrite = fn();
const onClose = fn();

const meta: Meta<typeof ProjectNavEditor> = {
  title: "Components/ProjectNavEditor",
  component: ProjectNavEditor,
  args: { projectId: NAV_PROJECT_ID, items: buildProjectNavItems(), onClose },
  beforeEach: () => {
    onWrite.mockClear();
    onClose.mockClear();
  },
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof ProjectNavEditor>;

function withPrefs(ui_preferences: Record<string, UiPreferenceValue>, rejectWith?: Error) {
  return (Story: () => React.ReactNode) => (
    <RecordingAuth user={buildUser({ ui_preferences })} onWrite={onWrite} rejectWith={rejectWith}>
      {Story()}
    </RecordingAuth>
  );
}

const dialog = () => within(within(document.body).getByRole("dialog", { name: "Customise navigation" }));
const rowLabels = (section: string) =>
  within(within(document.body).getByRole("region", { name: section }))
    .queryAllByRole("listitem")
    .map((li) => li.textContent?.replace(/Always visible/, "").trim());

export const ReorderMoveAndSaveForAllProjects: Story = {
  decorators: [withPrefs({})],
  play: async () => {
    const d = dialog();
    await expect(rowLabels("Navigation")).toEqual(["Overview", "Requirements", "Actions", "Reports", "Project admin", "Decisions"]);

    await userEvent.click(d.getByRole("button", { name: "Move Reports up" }));
    await userEvent.click(d.getByRole("button", { name: "Move Requirements to More" }));
    await expect(rowLabels("Navigation")).toEqual(["Overview", "Reports", "Actions", "Project admin", "Decisions"]);
    await expect(rowLabels("More")).toEqual(["Requirements"]);

    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(onWrite).toHaveBeenCalledTimes(1));
    await expect(onWrite).toHaveBeenCalledWith({
      project_nav: {
        order: ["overview", "reports", "actions", "admin", "decisions:/projects/project-1/decisions", "requirements"],
        more: ["requirements"],
      },
    });
    await expect(onClose).toHaveBeenCalled();
    await expect(await within(document.body).findByText("Navigation saved")).toBeInTheDocument();
  },
};

export const OnlyThisProjectWritesTheOverrideKey: Story = {
  decorators: [withPrefs({})],
  play: async () => {
    const d = dialog();
    await userEvent.click(d.getByRole("radio", { name: "Only this project" }));
    await userEvent.click(d.getByRole("button", { name: "Move Actions down" }));
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(onWrite).toHaveBeenCalledTimes(1));
    const patch = onWrite.mock.calls[0][0] as Record<string, UiPreferenceValue | null>;
    await expect(Object.keys(patch)).toEqual([`project_nav:${NAV_PROJECT_ID}`]);
  },
};

export const PinnedItemsHaveNoMoveToMoreControl: Story = {
  decorators: [withPrefs({})],
  play: async () => {
    const d = dialog();
    await expect(d.queryByRole("button", { name: "Move Overview to More" })).not.toBeInTheDocument();
    await expect(d.queryByRole("button", { name: "Move Project admin to More" })).not.toBeInTheDocument();
    await expect(d.getAllByText("Always visible")).toHaveLength(2);
    await expect(d.getByRole("button", { name: "Move Actions to More" })).toBeInTheDocument();
  },
};

export const EdgeMovesAreDisabled: Story = {
  decorators: [withPrefs({})],
  play: async () => {
    const d = dialog();
    await expect(d.getByRole("button", { name: "Move Overview up" })).toBeDisabled();
    await expect(d.getByRole("button", { name: "Move Decisions down" })).toBeDisabled();
  },
};

export const ResetToDefaultRestoresProductOrderUntilSaved: Story = {
  decorators: [
    withPrefs({
      project_nav: {
        order: ["overview", "reports", "requirements", "actions", "admin", "decisions:/projects/project-1/decisions"],
        more: ["actions"],
      },
    }),
  ],
  play: async () => {
    const d = dialog();
    await expect(rowLabels("More")).toEqual(["Actions"]);
    await userEvent.click(d.getByRole("button", { name: "Reset to default" }));
    await expect(rowLabels("Navigation")).toEqual(["Overview", "Requirements", "Actions", "Reports", "Project admin", "Decisions"]);
    await expect(rowLabels("More")).toEqual([]);
    // A draft only: nothing was written.
    await expect(onWrite).not.toHaveBeenCalled();
  },
};

export const SavingForAllReplacesThisProjectsOverride: Story = {
  decorators: [
    withPrefs({ [`project_nav:${NAV_PROJECT_ID}`]: { order: ["actions"], more: [] } }),
  ],
  play: async () => {
    const d = dialog();
    // An existing override pre-selects the project scope.
    await expect(d.getByRole("radio", { name: "Only this project" })).toBeChecked();
    await userEvent.click(d.getByRole("radio", { name: "All projects" }));
    await expect(d.getByText(/also replaces this project's own layout/)).toBeInTheDocument();
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(onWrite).toHaveBeenCalledTimes(1));
    const patch = onWrite.mock.calls[0][0] as Record<string, UiPreferenceValue | null>;
    await expect(patch[`project_nav:${NAV_PROJECT_ID}`]).toBeNull();
    await expect(patch.project_nav).toBeTruthy();
  },
};

export const RemoveOverrideDeletesOnlyTheOverrideKey: Story = {
  decorators: [
    withPrefs({ [`project_nav:${NAV_PROJECT_ID}`]: { order: ["actions"], more: [] } }),
  ],
  play: async () => {
    const d = dialog();
    await userEvent.click(d.getByRole("button", { name: "Remove this project's own layout" }));
    await expect(onWrite).toHaveBeenCalledWith({ [`project_nav:${NAV_PROJECT_ID}`]: null });
    await expect(onClose).toHaveBeenCalled();
  },
};

export const RemoveOverrideButtonOnlyShownWhenOverrideExists: Story = {
  decorators: [withPrefs({})],
  play: async () => {
    await expect(dialog().queryByRole("button", { name: "Remove this project's own layout" })).not.toBeInTheDocument();
  },
};

export const SavePrunesOverridesForUnreachableProjects: Story = {
  decorators: [
    withPrefs({ "project_nav:gone-project": { order: ["actions"], more: [] }, "project_nav:kept-project": { order: ["actions"], more: [] } }),
  ],
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.startsWith("/api/v1/projects?archived=false")) return [{ id: "kept-project" }] as ProjectListItem[];
      if (path.startsWith("/api/v1/projects?archived=true")) return [] as ProjectListItem[];
      throw new Error(`unmocked GET: ${path}`);
    });
  },
  play: async () => {
    await userEvent.click(dialog().getByRole("button", { name: "Save" }));
    await waitFor(() => expect(onWrite).toHaveBeenCalledTimes(1));
    const patch = onWrite.mock.calls[0][0] as Record<string, UiPreferenceValue | null>;
    await expect(patch["project_nav:gone-project"]).toBeNull();
    await expect(patch).not.toHaveProperty("project_nav:kept-project");
  },
};

export const SaveKeepsOverridesWhenReachabilityIsUnknown: Story = {
  decorators: [withPrefs({ "project_nav:other": { order: ["actions"], more: [] } })],
  beforeEach: () => {
    spyOn(api, "get").mockRejectedValue(new Error("network down"));
  },
  play: async () => {
    await userEvent.click(dialog().getByRole("button", { name: "Save" }));
    await waitFor(() => expect(onWrite).toHaveBeenCalledTimes(1));
    await expect(onWrite.mock.calls[0][0]).not.toHaveProperty("project_nav:other");
  },
};

export const CancelWritesNothing: Story = {
  decorators: [withPrefs({})],
  play: async () => {
    await userEvent.click(dialog().getByRole("button", { name: "Cancel" }));
    await expect(onClose).toHaveBeenCalled();
    await expect(onWrite).not.toHaveBeenCalled();
  },
};

export const FailedSaveShowsErrorKeepsDraftAndDoesNotClaimSuccess: Story = {
  decorators: [withPrefs({}, new Error("UI preferences are limited to 32 KiB in total."))],
  play: async () => {
    const d = dialog();
    await userEvent.click(d.getByRole("button", { name: "Move Actions to More" }));
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await expect(await within(document.body).findByText("UI preferences are limited to 32 KiB in total.")).toBeInTheDocument();
    await expect(within(document.body).queryByText("Navigation saved")).not.toBeInTheDocument();
    // Still open with the draft intact, and Save is usable again for a retry.
    await expect(onClose).not.toHaveBeenCalled();
    await expect(rowLabels("More")).toEqual(["Actions"]);
    await expect(d.getByRole("button", { name: "Save" })).toBeEnabled();
  },
};

export const FailedOverrideRemovalShowsErrorAndStaysOpen: Story = {
  decorators: [
    withPrefs({ [`project_nav:${NAV_PROJECT_ID}`]: { order: ["actions"], more: [] } }, new Error("Network error")),
  ],
  play: async () => {
    await userEvent.click(dialog().getByRole("button", { name: "Remove this project's own layout" }));
    await expect(await within(document.body).findByText("Network error")).toBeInTheDocument();
    await expect(within(document.body).queryByText("This project's own layout removed")).not.toBeInTheDocument();
    await expect(onClose).not.toHaveBeenCalled();
  },
};
