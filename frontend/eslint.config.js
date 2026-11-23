import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

// N-E-07: a mechanical style/correctness gate, not exhaustive Google
// JavaScript Style Guide enforcement — recommended rule sets for
// TypeScript, React hooks, and Fast Refresh correctness catch real drift
// without requiring a disruptive repo-wide reformat.
export default tseslint.config(
  { ignores: ["dist", "storybook-static", ".storybook", "coverage"] },
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
      // Context modules colocate a Provider component with its paired hook (and, for LoginPage,
      // one small pure helper); splitting them would only serve fast-refresh granularity and
      // scatter coupled code. `allowExportNames` is the plugin's documented escape hatch, so
      // the known non-component exports are listed instead of silencing the rule.
      "react-refresh/only-export-components": [
        "warn",
        {
          allowConstantExport: true,
          allowExportNames: [
            "useAuth",
            "useTheme",
            "useTerm",
            "useTermPlural",
            "useStrings",
            "useOrgLogoFileId",
            "useViewMode",
            "resolveLandingPath",
            "tabPanelProps",
            "useToast",
            "toErrorMessage",
            "resolveEffectiveTheme",
            "useFavourites",
            "useBranding",
            "useOrgLabel",
            "useOrgLabelCapitalized",
            "useOrgLabelPlural",
            "useFileUploadsEnabled",
          ],
        },
      ],
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
      // A warning (not disabled): this React-Compiler-derived rule flags React's documented
      // fetch-in-effect pattern (an async function doing `setX(null); await fetch(...); setY(data)`,
      // called from a useEffect keyed on filter/id deps) with no clean fix. `useEffectEvent`
      // does not silence it, because the rule propagates its "contains setState" flag through
      // it, and the patterns that satisfy the analysis (a nested `.then()`, `setTimeout`,
      // `startTransition`) only evade it. This is an unresolved upstream false positive
      // (facebook/react#34905, #34743, #34858; fix proposed in #36734).
      "react-hooks/set-state-in-effect": "warn",
    },
  }
);
