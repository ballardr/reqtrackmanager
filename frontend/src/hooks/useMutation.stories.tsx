import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { ProjectContext } from "../context/ProjectContextValue";
import { useMutation } from "./useMutation";

/** Runs one succeeding and one failing call, and shows whether the follow-up work ran. */
function Harness() {
  const run = useMutation();
  const [followed, setFollowed] = useState("");

  async function go(action: () => Promise<unknown>, verb: "add" | "delete", noun: string) {
    setFollowed((await run(action, verb, noun)) ? "followed" : "stopped");
  }

  return (
    <div className="stack">
      <button onClick={() => go(async () => undefined, "add", "{stage}")}>Add stage</button>
      <button onClick={() => go(async () => { throw new Error("A stage with that name already exists."); }, "add", "{stage}")}>Add duplicate</button>
      <button onClick={() => go(async () => { throw "not an Error"; }, "delete", "category")}>Delete odd failure</button>
      <button onClick={async () => setFollowed((await run(async () => undefined, { failure: "x" })) ? "followed" : "stopped")}>Quiet success</button>
      <output>{followed}</output>
    </div>
  );
}

const meta: Meta<typeof Harness> = {
  title: "Hooks/useMutation",
  component: Harness,
};
export default meta;

type Story = StoryObj<typeof Harness>;

export const SuccessShowsAToastAndLetsTheCallerContinue: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Add stage" }));
    await waitFor(() => expect(within(document.body).getByText("Stage added.")).toBeInTheDocument());
    await expect(canvasElement.querySelector("output")).toHaveTextContent("followed");
  },
};

export const FailureShowsTheServerMessageAndStopsTheCaller: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Add duplicate" }));
    await waitFor(() => expect(within(document.body).getByText("A stage with that name already exists.")).toBeInTheDocument());
    await expect(canvasElement.querySelector("output")).toHaveTextContent("stopped");
  },
};

export const ANonErrorFailureFallsBackToTheGeneratedMessage: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Delete odd failure" }));
    await waitFor(() => expect(within(document.body).getByText("Could not delete the category.")).toBeInTheDocument());
  },
};

export const NounsUseTheProjectsOwnTerminology: Story = {
  decorators: [
    (Story) => (
      <ProjectContext.Provider value={{ terminology: { stage: "phase" } }}>
        <Story />
      </ProjectContext.Provider>
    ),
  ],
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Add stage" }));
    await waitFor(() => expect(within(document.body).getByText("Phase added.")).toBeInTheDocument());
  },
};

export const QuietSuccessShowsNoToast: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Quiet success" }));
    await waitFor(() => expect(canvasElement.querySelector("output")).toHaveTextContent("followed"));
    await expect(within(document.body).queryByText("x")).not.toBeInTheDocument();
  },
};
