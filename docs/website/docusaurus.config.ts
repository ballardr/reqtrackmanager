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
        src: 'img/logo.svg',
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
          label: 'GitHub',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'Docs',
          items: [
            {
              label: 'Introduction',
              to: '/docs/introduction/overview',
            },
            {
              label: 'Installation & Deployment',
              to: '/docs/installation-deployment/overview',
            },
          ],
        },
        {
          title: 'More',
          items: [
            {
              label: 'GitHub',
              href: 'https://github.com/ballardr/reqtrackmanager',
            },
          ],
        },
      ],
      copyright: `Copyright © ${new Date().getFullYear()} ReqTrackManager contributors. Built with Docusaurus.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
    },
    // Themed to match the in-app dark header (--color-header-bg #14161c)
    // and accent green (--color-accent #2f855a / dark-mode #68d391) from
    // frontend/src/styles/theme.css, so every Mermaid diagram on the site
    // shares one deliberate look derived from the app's own palette rather
    // than the library default (docs/plans/docs-website-plan.md's
    // "Diagrams" decision).
    mermaid: {
      theme: {light: 'base', dark: 'base'},
      options: {
        themeVariables: {
          primaryColor: '#e8f5ee',
          primaryTextColor: '#14161c',
          primaryBorderColor: '#2f855a',
          lineColor: '#475569',
          secondaryColor: '#f1f5f9',
          tertiaryColor: '#ffffff',
          fontFamily:
            'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
        },
      },
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
