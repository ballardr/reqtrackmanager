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
          ],
        },
      ],
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
      // Downgraded to warn (not disabled): this React-Compiler-derived rule
      // flags React's own documented canonical fetch-in-effect pattern
      // (async function does `setX(null); await fetch(...); setY(data)`,
      // called from a useEffect keyed on filter/id deps — used throughout
      // this codebase's data-fetching pages) as an error, with no clean fix.
      // `useEffectEvent` does not silence it — it only removes stale-closure
      // deps, and the rule explicitly propagates its "contains setState"
      // flag through useEffectEvent wrappers. The only patterns that satisfy
      // the rule's static analysis (moving the setState into a nested
      // `.then()` callback, `setTimeout`, `startTransition`) are, by the
      // React community's and reporters' own description, "tricking the
      // lint rule" rather than a real fix. This is an open, unresolved,
      // Status:Unconfirmed upstream bug in React's compiler-derived lint
      // rules — see facebook/react#34905, #34743, #34858 (all report this
      // exact false positive against React's own docs' example) and the
      // in-flight, unmerged fix at facebook/react#36734. Revisit once that
      // lands upstream. (Decided by: User, 2026-09-15 — see
      // docs/react19-eslint10-upgrade-plan.md Phase 3.)
      "react-hooks/set-state-in-effect": "warn",
    },
  }
);
