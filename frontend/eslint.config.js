import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

// N-E-07: a mechanical style/correctness gate, not exhaustive Google
// JavaScript Style Guide enforcement — recommended rule sets for
// TypeScript, React hooks, and Fast Refresh correctness catch real drift
// without requiring a disruptive repo-wide reformat.
export default tseslint.config(
  { ignores: ["dist", "storybook-static", ".storybook"] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      globals: { window: "readonly", document: "readonly" },
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // Context modules intentionally colocate a Provider component with its
      // paired hook (and, for LoginPage, one small pure helper) — the
      // idiomatic React pattern this codebase uses throughout. Splitting
      // each into its own file would only serve fast-refresh's dev-time HMR
      // granularity, at the cost of scattering tightly-coupled code across
      // more files; `allowExportNames` is the plugin's own documented
      // escape hatch for exactly this case, so list the specific known
      // non-component exports rather than silencing the rule broadly.
      "react-refresh/only-export-components": [
        "warn",
        {
          allowConstantExport: true,
          allowExportNames: [
            "useAuth",
            "useTheme",
            "useTerm",
            "useTermPlural",
            "useOrgLogoFileId",
            "useViewMode",
            "resolveLandingPath",
          ],
        },
      ],
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
    },
  }
);
