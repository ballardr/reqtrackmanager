import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import { clearReturnTo, normaliseReturnTo, peekReturnTo, rememberReturnTo, takeReturnTo } from "./returnTo";

/** Pure-function checks for the sign-in return path, run as stories like the other helpers. */
const meta: Meta = { title: "Utils/ReturnTo" };
export default meta;

type Story = StoryObj;

export const KeepsALocalPathWithItsQueryAndHash: Story = {
  render: () => <div>Local paths</div>,
  play: async () => {
    await expect(normaliseReturnTo("/projects/p1/requirements?status=open#top")).toBe("/projects/p1/requirements?status=open#top");
    await expect(normaliseReturnTo("/notifications/abc")).toBe("/notifications/abc");
    await expect(normaliseReturnTo("/loginfoo")).toBe("/loginfoo");
  },
};

export const RejectsAnotherOrigin: Story = {
  render: () => <div>Open redirect</div>,
  play: async () => {
    for (const hostile of [
      "//evil.example/x",
      "///evil.example",
      "/\\evil.example",
      "/\t/evil.example",
      "/\n/evil.example",
      "https://evil.example/x",
      "http://evil.example",
      "javascript:alert(1)",
      "data:text/html,x",
      "evil.example/x",
      "projects/p1",
      "",
      null,
      undefined,
      42,
      {},
    ]) {
      await expect(normaliseReturnTo(hostile)).toBeNull();
    }
  },
};

export const RejectsAuthenticationPagesAndTheRoot: Story = {
  render: () => <div>Authentication pages</div>,
  play: async () => {
    for (const path of [
      "/login",
      "/login/acme",
      "/Login",
      "/login?x=1",
      "/signup",
      "/forgot-password",
      "/reset-password?token=t",
      "/confirm-email",
      "/oidc-complete#token=t",
      "/projects/../login",
      "/",
    ]) {
      await expect(normaliseReturnTo(path)).toBeNull();
    }
  },
};

export const RejectsAnOversizedPath: Story = {
  render: () => <div>Oversized</div>,
  play: async () => {
    await expect(normaliseReturnTo(`/${"a".repeat(2100)}`)).toBeNull();
  },
};

export const ARememberedPathIsUsedOnce: Story = {
  render: () => <div>Used once</div>,
  play: async () => {
    clearReturnTo();
    rememberReturnTo("/projects/p1/actions?open=1");
    await expect(peekReturnTo()).toBe("/projects/p1/actions?open=1");
    await expect(takeReturnTo()).toBe("/projects/p1/actions?open=1");
    await expect(takeReturnTo()).toBeNull();
  },
};

export const AnInvalidPathDoesNotReplaceAValidOne: Story = {
  render: () => <div>Keeps the valid path</div>,
  play: async () => {
    clearReturnTo();
    rememberReturnTo("/favourites");
    rememberReturnTo("//evil.example");
    rememberReturnTo("/login");
    await expect(takeReturnTo()).toBe("/favourites");
  },
};

export const AValueWrittenToStorageIsValidatedOnRead: Story = {
  render: () => <div>Tampered storage</div>,
  play: async () => {
    clearReturnTo();
    sessionStorage.setItem("reqtrack:return-to", "//evil.example");
    await expect(takeReturnTo()).toBeNull();
    sessionStorage.setItem("reqtrack:return-to", "https://evil.example");
    await expect(peekReturnTo()).toBeNull();
    clearReturnTo();
  },
};

export const ClearingForgetsThePath: Story = {
  render: () => <div>Cleared</div>,
  play: async () => {
    rememberReturnTo("/favourites");
    clearReturnTo();
    await expect(peekReturnTo()).toBeNull();
    await expect(sessionStorage.getItem("reqtrack:return-to")).toBeNull();
  },
};
