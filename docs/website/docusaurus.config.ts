import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

// This runs in Node.js - Don't use client-side code here (browser APIs, JSX...)

const config: Config = {
  title: 'ReqTrackManager',
  tagline:
    'An open-source engineering requirements management system (ERMS)',
  favicon: 'img/favicon.ico',

  // Future flags, see https://docusaurus.io/docs/api/docusaurus-config#future
  future: {
    v4: true, // Improve compatibility with the upcoming Docusaurus v4
  },

  // GitHub Pages project-site hosting: https://ballardr.github.io/reqtrackmanager/
  url: 'https://ballardr.github.io',
  baseUrl: '/reqtrackmanager/',

  // GitHub pages deployment config.
  organizationName: 'ballardr',
  projectName: 'reqtrackmanager',

  // Fail the build (and therefore CI) on any dangling internal link/anchor -
  // this is the mechanism that makes "every page exists and is linked"
  // actually enforced rather than aspirational (docs/plans/docs-website-plan.md).
  onBrokenLinks: 'throw',
  onBrokenAnchors: 'throw',

  // No i18n in this plan yet - matches frontend/'s own single-locale-for-now
  // state (see docs/decisions.md's i18n note).
  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  markdown: {
    mermaid: true,
  },
  themes: ['@docusaurus/theme-mermaid'],

  presets: [
    [
      'classic',
      {
        docs: {
          sidebarPath: './sidebars.ts',
          editUrl:
            'https://github.com/ballardr/reqtrackmanager/tree/main/docs/website/',
        },
        // Documentation, not a blog.
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  plugins: [
    [
      '@easyops-cn/docusaurus-search-local',
      {
        hashed: true,
        language: ['en'],
      },
    ],
    [
      '@docusaurus/plugin-client-redirects',
      {
        // No separate homepage - `/` should land a visitor straight on the
        // docs' own front page rather than a hero/"Read the docs" page in
        // between. The navbar logo's `href` below is pointed at the same
        // target rather than left at its `/` default, so nothing else in
        // the site links to `/` itself for onBrokenLinks to validate.
        redirects: [
          {
            from: '/',
            to: '/docs/introduction/overview',
          },
        ],
      },
    ],
  ],

  themeConfig: {
    image: 'img/screenshots/project-overview.png',
    colorMode: {
      respectPrefersColorScheme: true,
    },
    navbar: {
      title: 'ReqTrackManager',
      logo: {
        alt: 'ReqTrackManager logo',
        href: '/docs/introduction/overview',
        src: 'img/logo.svg',
        // Matches the app's own header logo height (Layout.tsx's
        // `style={{height: 24}}` on the same mark) rather than Infima's
        // 2rem/32px navbar-logo default. This renders as a plain `height`
        // attribute on the <img>, which Infima's own
        // `.navbar__logo img { height: 100% }` (default.css) overrides
        // regardless of the number here - src/css/custom.css carries the
        // rule that actually enforces it; kept here too so the intended
        // size ships even if that CSS override is ever removed, and to
        // avoid a layout shift on first paint.
        height: 24,
      },
      items: [
        {
          type: 'docSidebar',
          sidebarId: 'docsSidebar',
          position: 'left',
          label: 'Docs',
        },
        {
          href: 'https://github.com/ballardr/reqtrackmanager',
          label: 'Repository',
          position: 'left',
        },
        {
          href: 'https://github.com/sponsors/ballardr/',
          label: 'Sponsor',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'dark',
      // Docs/GitHub link columns removed at the user's request (2026-09-15)
      // - both are already one click away via the navbar, so the footer is
      // just the copyright line now.
      links: [],
      copyright: `Copyright © ${new Date().getFullYear()} Richard Ballard. Built with Docusaurus.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
    },
    // Node fill/border use a blue tint, a deliberate choice distinct from
    // the app's own green accent (--color-accent #2f855a / dark-mode
    // #68d391, still used for the site's navbar/links/chrome via
    // src/css/custom.css) - blue reads more clearly as a *diagram*
    // palette and was requested specifically for that reason, so this
    // page's node color no longer tracks the app's brand color 1:1
    // per the original "Diagrams" decision (docs/plans/docs-website-plan.md).
    //
    // @docusaurus/theme-mermaid only swaps the *named* base theme between
    // light/dark (see useMermaidConfig in its client code) - `options`
    // (and therefore themeVariables below) is one static object applied
    // in both color modes. Node/actor/cluster fills are safe to hardcode
    // because they always render as an opaque "card" (fill + border) that
    // never touches the real page background, so their contrast is fixed
    // regardless of site color mode. But anything Mermaid draws with no
    // fill behind it - edges, arrowheads, and sequence-diagram signal
    // lines/labels - is painted directly over the page's own background,
    // which *does* flip between white and near-black
    // (--ifm-background-color). Two concrete bugs from that were found in
    // Phase 10's visual QA pass:
    //  1. lineColor (#475569) had 7.6:1 contrast against a light page but
    //     only 2.3:1 against the dark one - comfortably readable in light
    //     mode, close to invisible in dark mode. Fixed by moving to a
    //     mid-tone slate (#6b7a94) chosen at the luminance where contrast
    //     against white and against near-black are equal (~4.3:1 both
    //     ways) - the best any single static color can do for a value
    //     that must work on both a black and white background, clearing
    //     WCAG's 3:1 non-text threshold with margin in both modes.
    //  2. arrowheadColor and signalColor/signalTextColor (sequence-diagram
    //     message lines/labels) were never set, so Mermaid fell back to
    //     invert(background) using the 'base' theme's own light default
    //     background (#f4f4f4) - i.e. black, regardless of site color
    //     mode. Black arrowheads/signal lines are invisible against the
    //     dark-mode page background. Fixed by pinning them to the same
    //     balanced slate as lineColor.
    // primaryBorderColor is a solid 7.5:1 against its own node fill (was
    // a green at 4.1:1 before the blue swap above), and
    // secondaryBorderColor/tertiaryBorderColor are set explicitly rather
    // than left to Mermaid's default derivation, which only
    // lightens/darkens the matching fill by ~10% - on tertiaryColor
    // (#ffffff) that default produces a near-white border on a white
    // cluster/note fill, effectively invisible in either site color mode.
    mermaid: {
      theme: {light: 'base', dark: 'base'},
      options: {
        themeVariables: {
          primaryColor: '#e6f0fa',
          primaryTextColor: '#14161c',
          primaryBorderColor: '#1a4d80',
          lineColor: '#6b7a94',
          arrowheadColor: '#6b7a94',
          signalColor: '#6b7a94',
          signalTextColor: '#6b7a94',
          secondaryColor: '#f1f5f9',
          secondaryBorderColor: '#6b7a94',
          tertiaryColor: '#ffffff',
          tertiaryBorderColor: '#6b7a94',
          fontFamily:
            'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
        },
      },
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
