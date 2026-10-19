import type { Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { expect, waitFor, within } from "storybook/test";

import { PeopleRedirect } from "./PeopleRedirect";

/** Shows where the router ended up, so the story can assert the redirect target. */
function Where() {
  const { pathname, search } = useLocation();
  return <p data-testid="where">{pathname + search}</p>;
}

function Harness({ kind }: { kind: "persona" | "stakeholder" | "need" }) {
  return (
    <MemoryRouter initialEntries={["/projects/project-1/modules/stakeholders/old-list"]}>
      <Routes>
        <Route path="/projects/:projectId/modules/stakeholders/old-list" element={<PeopleRedirect kind={kind} />} />
        <Route path="*" element={<Where />} />
      </Routes>
    </MemoryRouter>
  );
}

const meta: Meta<typeof Harness> = { title: "Modules/Stakeholders/PeopleRedirect", component: Harness };
export default meta;

type Story = StoryObj<typeof Harness>;

/** An old per-type list route lands on People with that kind selected. */
export const PersonaListRedirectsToPeople: Story = {
  args: { kind: "persona" },
  play: async ({ canvasElement }) => {
    await waitFor(() =>
      expect(within(canvasElement).getByTestId("where")).toHaveTextContent("/projects/project-1/modules/stakeholders/people?kind=persona"),
    );
  },
};

export const NeedListRedirectsToPeople: Story = {
  args: { kind: "need" },
  play: async ({ canvasElement }) => {
    await waitFor(() =>
      expect(within(canvasElement).getByTestId("where")).toHaveTextContent("/projects/project-1/modules/stakeholders/people?kind=need"),
    );
  },
};
