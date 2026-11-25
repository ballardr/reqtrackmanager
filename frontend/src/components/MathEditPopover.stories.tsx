import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { MathToolbarButton } from "./MathEditPopover";

/** The equation panel and the toolbar buttons that open it. */
const meta: Meta = { title: "Components/MathEditPopover" };
export default meta;

type Story = StoryObj;

/** Both buttons beside a record of what the editor was asked to insert. */
function Harness({ selection = "", onApply }: { selection?: string; onApply?: (tex: string, display: boolean) => void }) {
  const [last, setLast] = useState("");
  const apply = (tex: string, display: boolean) => { setLast(`${display ? "block" : "inline"}:${tex}`); onApply?.(tex, display); };
  return (
    <>
      <div className="row">
        <MathToolbarButton display={false} readSelection={() => selection} onApply={apply} />
        <MathToolbarButton display readSelection={() => selection} onApply={apply} />
      </div>
      <p data-testid="last">{last}</p>
    </>
  );
}

export const OpensWithTheSelectedTextAndDrawsItLive: Story = {
  render: () => <Harness selection="x^2 + y^2" />,
  play: async ({ canvasElement }) => {
    const page = within(document.body);
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Inline equation" }));
    await expect(await page.findByRole("textbox", { name: "TeX" })).toHaveValue("x^2 + y^2");
    await waitFor(() => expect(page.getByTestId("math-preview").querySelector(".katex")).not.toBeNull());
    await userEvent.type(page.getByRole("textbox", { name: "TeX" }), " = z^2");
    await waitFor(() => expect(page.getByTestId("math-preview")).toHaveTextContent("z"));
  },
};

export const InsertReportsTheTeXAndWhetherItIsABlock: Story = {
  render: () => <Harness onApply={fn()} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const page = within(document.body);
    await userEvent.click(canvas.getByRole("button", { name: "Equation block" }));
    await userEvent.type(await page.findByRole("textbox", { name: "TeX" }), "\\frac{{a}{{b}");
    await userEvent.click(page.getByRole("button", { name: "Insert" }));
    await expect(canvas.getByTestId("last")).toHaveTextContent("block:\\frac{a}{b}");
    await waitFor(() => expect(page.queryByRole("textbox", { name: "TeX" })).toBeNull());
  },
};

export const InsertIsUnavailableUntilThereIsAnEquation: Story = {
  render: () => <Harness />,
  play: async ({ canvasElement }) => {
    const page = within(document.body);
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Inline equation" }));
    await expect(await page.findByRole("button", { name: "Insert" })).toBeDisabled();
    await expect(page.getByTestId("math-preview")).toHaveTextContent("The equation is drawn here.");
  },
};

export const ACommandTheReportsCannotDrawIsRefusedWithAReason: Story = {
  render: () => <Harness />,
  play: async ({ canvasElement }) => {
    const page = within(document.body);
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Inline equation" }));
    await userEvent.type(await page.findByRole("textbox", { name: "TeX" }), "\\href{x}{y}", { delay: 0 });
    await expect(await page.findByRole("alert")).toBeInTheDocument();
    await expect(page.getByRole("button", { name: "Insert" })).toBeDisabled();
  },
};

export const ATextThatEndsTheEquationEarlyIsRefused: Story = {
  render: () => <Harness />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const page = within(document.body);
    await userEvent.click(canvas.getByRole("button", { name: "Equation block" }));
    await userEvent.type(await page.findByRole("textbox", { name: "TeX" }), "a$$b");
    await expect(await page.findByRole("alert")).toHaveTextContent("cannot contain $$");
    await expect(page.getByRole("button", { name: "Insert" })).toBeDisabled();
  },
};

export const EscapeClosesThePanelWithoutInserting: Story = {
  render: () => <Harness selection="x" />,
  play: async ({ canvasElement }) => {
    const page = within(document.body);
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Inline equation" }));
    // Focus moves into the panel on opening, so Escape reaches it.
    await waitFor(async () => expect(await page.findByRole("textbox", { name: "TeX" })).toHaveFocus());
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(page.queryByRole("textbox", { name: "TeX" })).toBeNull());
    await expect(within(canvasElement).getByTestId("last")).toHaveTextContent("");
  },
};
