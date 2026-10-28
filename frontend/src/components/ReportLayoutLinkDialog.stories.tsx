import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, screen, userEvent, waitFor, within } from "storybook/test";

import { requiredCaptions } from "../testing/requiredMarkers";
import { ReportLayoutLinkDialog } from "./ReportLayoutLinkDialog";

/** The link dialog of the document view: a web address, an email address or a section of the same document. */
const meta: Meta<typeof ReportLayoutLinkDialog> = {
  title: "Components/ReportLayoutLinkDialog",
  component: ReportLayoutLinkDialog,
  args: {
    initialHref: "", sections: [{ label: "Overview", anchor: "overview" }, { label: "Scope & Goals", anchor: "scope-goals" }],
    onApply: fn(), onClose: fn(),
  },
};
export default meta;

type Story = StoryObj<typeof ReportLayoutLinkDialog>;

const dialog = async () => within(await screen.findByRole("dialog", { name: "Link" }));

export const AWebAddressIsCheckedAsItIsTyped: Story = {
  play: async ({ args }) => {
    const d = await dialog();
    const apply = d.getByRole("button", { name: "Apply" });
    await expect(apply).toBeDisabled();
    await userEvent.type(d.getByRole("textbox", { name: /Web address/ }), "javascript:alert(1)");
    await expect(await d.findByRole("alert")).toHaveTextContent("Only web (http, https), email (mailto) and section (#) links are allowed.");
    await expect(apply).toBeDisabled();
    await userEvent.clear(d.getByRole("textbox", { name: /Web address/ }));
    await userEvent.type(d.getByRole("textbox", { name: /Web address/ }), "https://example.org/spec");
    await waitFor(() => expect(apply).toBeEnabled());
    await userEvent.click(apply);
    await expect(args.onApply).toHaveBeenCalledWith("https://example.org/spec");
  },
};

export const ARequiredFieldIsMarked: Story = {
  play: async () => {
    const dialogEl = await screen.findByRole("dialog", { name: "Link" });
    await expect(requiredCaptions(dialogEl)).toEqual(["Link to", "Web address"]);
  },
};

export const AnEmailAddressBecomesAMailtoLink: Story = {
  play: async ({ args }) => {
    const d = await dialog();
    await userEvent.selectOptions(d.getByRole("combobox", { name: /Link to/ }), "email");
    await userEvent.type(d.getByRole("textbox", { name: /Email address/ }), "team@example.org");
    await userEvent.click(d.getByRole("button", { name: "Apply" }));
    await expect(args.onApply).toHaveBeenCalledWith("mailto:team@example.org");
  },
};

export const ANotAnEmailAddressIsRefused: Story = {
  play: async () => {
    const d = await dialog();
    await userEvent.selectOptions(d.getByRole("combobox", { name: /Link to/ }), "email");
    await userEvent.type(d.getByRole("textbox", { name: /Email address/ }), "not an address");
    await expect(await d.findByRole("alert")).toBeInTheDocument();
    await expect(d.getByRole("button", { name: "Apply" })).toBeDisabled();
  },
};

export const ASectionIsPickedFromTheHeadings: Story = {
  play: async ({ args }) => {
    const d = await dialog();
    await userEvent.selectOptions(d.getByRole("combobox", { name: /Link to/ }), "section");
    const section = d.getByRole("combobox", { name: /^Section/ }) as HTMLSelectElement;
    await expect(Array.from(section.options).map((o) => o.text)).toEqual(["Choose a section…", "Overview", "Scope & Goals"]);
    await userEvent.selectOptions(section, "scope-goals");
    await userEvent.click(d.getByRole("button", { name: "Apply" }));
    await expect(args.onApply).toHaveBeenCalledWith("#scope-goals");
  },
};

export const WithNoHeadingsASectionLinkSaysSo: Story = {
  args: { sections: [] },
  play: async () => {
    const d = await dialog();
    await userEvent.selectOptions(d.getByRole("combobox", { name: /Link to/ }), "section");
    await expect(d.getByText("This layout has no headings to link to yet.")).toBeInTheDocument();
    await expect(d.getByRole("button", { name: "Apply" })).toBeDisabled();
  },
};

export const AnAddressMayUseAValueFilledInLater: Story = {
  play: async ({ args }) => {
    const d = await dialog();
    const box = d.getByRole("textbox", { name: /Web address/ });
    await userEvent.type(box, "{{{{record.url}}");
    await waitFor(() => expect(d.getByRole("button", { name: "Apply" })).toBeEnabled());
    await userEvent.clear(box);
    await userEvent.type(box, "https://example.org/{{{{record.code}}");
    await userEvent.click(d.getByRole("button", { name: "Apply" }));
    await expect(args.onApply).toHaveBeenCalledWith("https://example.org/{{record.code}}");
  },
};

export const AValueInAnAddressDoesNotExcuseABadOne: Story = {
  play: async () => {
    const d = await dialog();
    await userEvent.type(d.getByRole("textbox", { name: /Web address/ }), "javascript:{{{{record.code}}");
    await expect(await d.findByRole("alert")).toBeInTheDocument();
    await expect(d.getByRole("button", { name: "Apply" })).toBeDisabled();
  },
};

export const AnExistingLinkIsShownAndCanBeRemoved: Story = {
  args: { initialHref: "https://example.org/old", onRemove: fn() },
  play: async ({ args }) => {
    const d = await dialog();
    await expect(d.getByRole("textbox", { name: /Web address/ })).toHaveValue("https://example.org/old");
    await userEvent.click(d.getByRole("button", { name: "Remove link" }));
    await expect(args.onRemove).toHaveBeenCalled();
  },
};

export const AnExistingSectionLinkOpensOnItsKindAndSection: Story = {
  args: { initialHref: "#overview" },
  play: async () => {
    const d = await dialog();
    await expect((d.getByRole("combobox", { name: /Link to/ }) as HTMLSelectElement).value).toBe("section");
    await expect((d.getByRole("combobox", { name: /^Section/ }) as HTMLSelectElement).value).toBe("overview");
  },
};

export const ASectionThatNoLongerExistsStaysVisibleNotSilentlyChanged: Story = {
  args: { initialHref: "#gone" },
  play: async () => {
    const d = await dialog();
    const section = d.getByRole("combobox", { name: /^Section/ }) as HTMLSelectElement;
    await expect(section.value).toBe("gone");
  },
};

export const CancelCloses: Story = {
  play: async ({ args }) => {
    await userEvent.click((await dialog()).getByRole("button", { name: "Cancel" }));
    await expect(args.onClose).toHaveBeenCalled();
  },
};
