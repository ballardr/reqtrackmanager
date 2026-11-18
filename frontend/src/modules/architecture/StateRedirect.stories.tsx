import type { Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { expect, spyOn, waitFor, within } from "storybook/test";

import { api, ApiError } from "../../api/client";
import { buildState, PROJECT_ID } from "./architectureFixtures";
import { StateRedirect } from "./StateRedirect";

/** Shows the address the redirect led to. */
function Address() {
  const location = useLocation();
  return <p data-testid="address">{location.pathname + location.search}</p>;
}

const meta: Meta<typeof StateRedirect> = {
  title: "Modules/Architecture/StateRedirect",
  component: StateRedirect,
  // The state's own route is the redirect; every other address (where it sends the person) just shows itself.
  decorators: [
    (Story) => (
      <MemoryRouter initialEntries={[`/projects/${PROJECT_ID}/modules/architecture/states/ste-1`]}>
        <Routes>
          <Route path="/projects/:projectId/modules/architecture/states/:stateId" element={<Story />} />
          <Route path="*" element={<Address />} />
        </Routes>
      </MemoryRouter>
    ),
  ],
};
export default meta;

type Story = StoryObj<typeof StateRedirect>;

/** A link to a state opens its state machine diagram with the state selected (the address names it). */
export const OpensTheDiagramWithTheStateSelected: Story = {
  beforeEach: () => { spyOn(api, "get").mockResolvedValue(buildState() as never); },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByTestId("address")).toHaveTextContent(
      `/projects/${PROJECT_ID}/modules/architecture/state-machine-diagrams/smd-1?state=ste-1`,
    ));
  },
};

/** A state that cannot be read shows a not-found message, never a spinner. */
export const AStateThatCannotBeReadShowsNotFound: Story = {
  beforeEach: () => { spyOn(api, "get").mockRejectedValue(new ApiError(404, "Not found")); },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText(/could not be found/)).toBeInTheDocument();
  },
};
