import type { Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { expect, spyOn, waitFor, within } from "storybook/test";

import { api, ApiError } from "../api/client";
import type { NotificationDetail } from "../api/types";
import { buildNotification } from "../testing/storybook-helpers";
import { NotificationOpenPage } from "./NotificationOpenPage";

/** Shows where the page navigated to, so a story can assert the destination without mounting that page. */
function Where() {
  const location = useLocation();
  return <div data-testid="where">{location.pathname}</div>;
}

const meta: Meta<typeof NotificationOpenPage> = {
  title: "Pages/NotificationOpenPage",
  component: NotificationOpenPage,
  decorators: [
    (Story) => (
      <MemoryRouter initialEntries={["/notifications/n1"]}>
        <Routes>
          <Route path="/notifications/:notificationId" element={<Story />} />
          <Route path="*" element={<Where />} />
        </Routes>
      </MemoryRouter>
    ),
  ],
};
export default meta;

type Story = StoryObj<typeof NotificationOpenPage>;

function mockNotification(overrides: Partial<NotificationDetail>) {
  const loaded: NotificationDetail = { ...buildNotification({ id: "n1" }), subject_available: true, ...overrides };
  spyOn(api, "get").mockResolvedValue(loaded);
  spyOn(api, "post").mockResolvedValue(undefined);
}

/** The click opens the subject and marks the notification read. */
export const OpensTheSubject: Story = {
  beforeEach: () =>
    mockNotification({
      type: "stage_phase_overdue", target_kinds: ["delivery_status"], entity_type: "project_stage", entity_id: "s-1", project_id: "p-1",
    }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByTestId("where")).toHaveTextContent("/projects/p-1/stage-phases"));
    await expect(api.post).toHaveBeenCalledWith("/api/v1/notifications/n1/read");
  },
};

/** A message with no page of its own is shown in full. */
export const ShowsAMessageWithNoPage: Story = {
  beforeEach: () =>
    mockNotification({
      type: "system_announcement", title: "Planned maintenance", body: "The platform restarts at 22:00.",
      target_kinds: ["detail"], entity_type: "announcement", entity_id: "a-1", project_id: null,
    }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("heading", { name: "Planned maintenance" })).toBeInTheDocument();
    await expect(canvas.getByText("The platform restarts at 22:00.")).toBeInTheDocument();
    await expect(canvas.queryByRole("status")).not.toBeInTheDocument();
  },
};

/** Revoked access ends on the message and states why, never on a page the person cannot open. */
export const ExplainsEndedAccess: Story = {
  beforeEach: () =>
    mockNotification({
      type: "permission_revoked", title: "Your access was removed", target_kinds: ["project"], project_id: "p-1",
      entity_type: null, entity_id: null, subject_available: false,
    }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("status")).toHaveTextContent("You no longer have access to the page this notification refers to.");
    await expect(canvas.queryByTestId("where")).not.toBeInTheDocument();
  },
};

/** A notification stored before the data that names its subject was recorded falls back to its message. */
export const FallsBackWhenTheDataIsMissing: Story = {
  beforeEach: () =>
    mockNotification({
      type: "permission_granted", title: "Organisation permission granted", target_kinds: ["standard", "organization", "project"],
      project_id: null, entity_type: null, entity_id: null,
    }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("heading", { name: "Organisation permission granted" })).toBeInTheDocument();
  },
};

/** Another person's notification, or one that no longer exists, says so. */
export const NotFound: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockRejectedValue(new ApiError(404, "Notification not found."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("alert")).toHaveTextContent("This notification was not found.");
  },
};

export const LightTheme: Story = { ...ShowsAMessageWithNoPage, globals: { theme: "light" } };
export const DarkTheme: Story = { ...ShowsAMessageWithNoPage, globals: { theme: "dark" } };
