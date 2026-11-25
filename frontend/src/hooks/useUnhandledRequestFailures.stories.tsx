import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, within } from "storybook/test";

import { ApiError } from "../api/client";
import { withToast } from "../testing/storybook-helpers";
import { failureText, useUnhandledRequestFailures } from "./useUnhandledRequestFailures";

/** Raises a failed request nobody handles, as a page does that loads with `.then(setRows)` and no catch. */
function Harness() {
  useUnhandledRequestFailures();
  const fail = (error: ApiError) => {
    // A rejected promise nobody awaits or catches; the event is dispatched directly so the test does not depend on the
    // runner's own handling of an unhandled rejection.
    window.dispatchEvent(new PromiseRejectionEvent("unhandledrejection", { promise: Promise.resolve(), reason: error }));
  };
  const ended = new ApiError(401, "Could not validate credentials.");
  ended.sessionEnded = true;
  return (
    <div className="stack">
      <button className="btn" onClick={() => fail(new ApiError(500, "Internal Server Error"))}>Fail a read</button>
      <button className="btn" onClick={() => fail(new ApiError(422, '[{"loc":["body","name"]}]'))}>Fail validation</button>
      <button className="btn" onClick={() => fail(ended)}>End the session</button>
      <button className="btn" onClick={() => window.dispatchEvent(new PromiseRejectionEvent("unhandledrejection", { promise: Promise.resolve(), reason: new Error("not a request") }))}>Fail elsewhere</button>
    </div>
  );
}

/**
 * The notice for a request failure no page handled: the reason once, with Reload, instead of a spinner that never ends.
 */
const meta: Meta<typeof Harness> = { title: "Hooks/useUnhandledRequestFailures", component: Harness, decorators: [withToast()] };
export default meta;

type Story = StoryObj<typeof Harness>;

export const ShowsTheReasonOnceWithReload: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    await userEvent.click(canvas.getByRole("button", { name: "Fail a read" }));
    await expect(await body.findByText("Internal Server Error")).toBeInTheDocument();
    await expect(body.getByText("Part of this page may not have loaded.")).toBeInTheDocument();
    await expect(body.getByRole("button", { name: "Reload" })).toBeInTheDocument();
    // The same failure again within the window is not stacked.
    await userEvent.click(canvas.getByRole("button", { name: "Fail a read" }));
    await expect(body.getAllByText("Internal Server Error")).toHaveLength(1);
  },
};

export const AValidationListIsNotReadAsASentence: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Fail validation" }));
    await expect(await within(document.body).findByText("A request could not be completed.")).toBeInTheDocument();
    await expect(failureText(new ApiError(422, '[{"loc":[]}]'), "g")).toBe("g");
    await expect(failureText(new ApiError(404, "Not found."), "g")).toBe("Not found.");
    await expect(failureText(new ApiError(500, "  "), "g")).toBe("g");
  },
};

/** A refusal that ended the session, and a failure that is not a request, show nothing. */
export const ASessionEndAndOtherErrorsShowNothing: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "End the session" }));
    await userEvent.click(canvas.getByRole("button", { name: "Fail elsewhere" }));
    await expect(within(document.body).queryByRole("button", { name: "Reload" })).not.toBeInTheDocument();
  },
};
