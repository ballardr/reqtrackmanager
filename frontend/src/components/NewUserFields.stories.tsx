import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { NewUserFields } from "./NewUserFields";
import { EMPTY_NEW_USER } from "./newUserValues";

const meta: Meta<typeof NewUserFields> = {
  title: "Components/NewUserFields",
  component: NewUserFields,
  args: { values: EMPTY_NEW_USER, onChange: fn() },
};
export default meta;

type Story = StoryObj<typeof NewUserFields>;

export const AllFieldsReportEdits: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByLabelText("Email"), "a");
    await expect(args.onChange).toHaveBeenCalledWith({ email: "a" });
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Role" }), "org_admin");
    await expect(args.onChange).toHaveBeenCalledWith({ role: "org_admin" });
    await expect(canvas.getByText("At least 8 characters.")).toBeInTheDocument();
  },
};

export const OptionalFieldsCanBeHidden: Story = {
  args: { show: { displayName: false, password: false, role: false } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByLabelText("Email")).toBeInTheDocument();
    await expect(canvas.queryByLabelText("Name")).not.toBeInTheDocument();
    await expect(canvas.queryByLabelText("Password")).not.toBeInTheDocument();
    await expect(canvas.queryByRole("combobox", { name: "Role" })).not.toBeInTheDocument();
  },
};
