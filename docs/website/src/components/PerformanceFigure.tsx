/**
 * Module: PerformanceFigure
 *
 * Shows one of the performance figures drawn by `perf/plot_results.py`, with the light or dark SVG that matches the
 * site's theme, and a caption stating what the figure shows and the conclusion drawn from it.
 *
 * Responsibilities:
 * - Pick `<name>-light.svg` or `<name>-dark.svg` from `static/img/performance/` by the active theme (Docusaurus's
 *   `ThemedImage`), resolved against the site's base URL.
 * - Render the image with its alternative text inside a `<figure>` with a visible caption.
 *
 * Design decisions:
 * - The figures are drawn on their own surface colour (light and dark), so they stay legible whichever theme the page
 *   shows; the caption is page text, so it follows the theme.
 *
 * Dependencies: `@docusaurus/useBaseUrl`, `@theme/ThemedImage`.
 */
import React from 'react';
import useBaseUrl from '@docusaurus/useBaseUrl';
import ThemedImage from '@theme/ThemedImage';

type Props = {
  /** The figure's file stem, for example `memory-by-project-size`. */
  name: string;
  /** What the figure shows, for a reader who cannot see it. */
  alt: string;
  /** One line: what the figure shows and the conclusion drawn from it. */
  caption: string;
};

/**
 * Renders a themed performance figure and its caption.
 *
 * @param props The figure's file stem, alternative text and caption.
 * @returns A `<figure>` element.
 */
export default function PerformanceFigure({name, alt, caption}: Props): React.JSX.Element {
  const sources = {
    light: useBaseUrl(`/img/performance/${name}-light.svg`),
    dark: useBaseUrl(`/img/performance/${name}-dark.svg`),
  };
  return (
    <figure style={{margin: '1.5rem 0'}}>
      <ThemedImage alt={alt} sources={sources} style={{maxWidth: '100%', height: 'auto', borderRadius: 6}} />
      <figcaption style={{fontSize: '0.9rem', marginTop: '0.5rem'}}>{caption}</figcaption>
    </figure>
  );
}
