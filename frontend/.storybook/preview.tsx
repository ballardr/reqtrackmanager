import type { Decorator, Preview } from "@storybook/react-vite";
import { useEffect } from "react";

import "../src/styles/theme.css";

/**
 * Applies the toolbar's selected theme (U-U-01: light and dark are both
 * first-class) the same way the real app does — a `data-theme` attribute
 * on <html>, read by src/styles/theme.css's CSS variables — so every story
 * renders with the actual product palette, not Storybook's own chrome.
 */
const withTheme: Decorator = (Story, context) => {
  const theme = context.globals.theme ?? "light";
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);
  return (
    <div style={{ background: "var(--color-bg)", color: "var(--color-text)", padding: "1rem", minHeight: "100vh" }}>
      <Story />
    </div>
  );
};

const preview: Preview = {
  parameters: {
    controls: {
      matchers: {
        color: /(background|color)$/i,
        date: /Date$/i,
      },
    },
    a11y: {
      // 'todo' - show a11y violations in the test UI only
      // 'error' - fail CI on a11y violations
      // 'off' - skip a11y checks entirely
      test: "todo",
    },
  },
  // A toolbar toggle (not just parameters) so switching light/dark while
  // browsing stories is one click, and so every story can be exercised in
  // both without writing two copies of it.
  globalTypes: {
    theme: {
      description: "Light/dark theme (U-U-01)",
      toolbar: {
        title: "Theme",
        icon: "circlehollow",
        items: [
          { value: "light", icon: "sun", title: "Light" },
          { value: "dark", icon: "moon", title: "Dark" },
        ],
        dynamicTitle: true,
      },
    },
  },
  initialGlobals: {
    theme: "light",
  },
  decorators: [withTheme],
};

export default preview;
