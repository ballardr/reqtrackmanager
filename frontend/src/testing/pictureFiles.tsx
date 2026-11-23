/**
 * Module: testing/pictureFiles
 *
 * Story fixture that makes the files `pic-*` load as real pictures. A story has no backend, so a file URL
 * (`/api/v1/files/<id>`) would fail to load and the thumbnail would fall back to its icon at an unpredictable moment.
 * `withPictureFiles` rewrites an `<img>` `src` attribute naming one of these ids to an inline data URI, so a story
 * can check a preview's size, backdrop and focus deterministically.
 *
 * Responsibilities: the fixture pictures (a transparent PNG, an SVG, a very wide, a very tall and a tiny picture) and
 * the decorator that installs the rewrite for the story's lifetime. Dependencies: `@storybook/react-vite` types.
 */
import type { Decorator } from "@storybook/react-vite";

const svg = (width: number, height: number, fill: string) =>
  `data:image/svg+xml;utf8,${encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">`
    + `<rect x="${width / 4}" y="${height / 4}" width="${width / 2}" height="${height / 2}" fill="${fill}"/></svg>`,
  )}`;

/** A 1 x 1 white PNG with a transparent surround stands in for a white logo. */
const TRANSPARENT_PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";

/** Fixture file id to the picture drawn for it. */
export const PICTURE_FILES: Record<string, string> = {
  "pic-png": TRANSPARENT_PNG,
  "pic-svg": svg(120, 80, "#2563eb"),
  "pic-wide": svg(1600, 120, "#16a34a"),
  "pic-tall": svg(120, 1600, "#dc2626"),
  "pic-tiny": svg(8, 8, "#9333ea"),
  "pic-large": svg(2000, 1500, "#0891b2"),
};

/** The id of a fixture file named by a file URL, or null. */
function fixtureId(url: string): string | null {
  const found = /\/api\/v1\/files\/(pic-[a-z]+)/.exec(url);
  return found && found[1] in PICTURE_FILES ? found[1] : null;
}

/** Replaces `src` writes (attribute and property) naming a fixture file with its inline picture; installed once. */
function installRewrite(): void {
  const proto = HTMLImageElement.prototype;
  if ((proto as { __pictureFiles?: boolean }).__pictureFiles) return;
  (proto as { __pictureFiles?: boolean }).__pictureFiles = true;
  const rewrite = (value: string) => {
    const id = fixtureId(String(value));
    return id ? PICTURE_FILES[id] : value;
  };
  const setAttribute = proto.setAttribute;
  proto.setAttribute = function (this: HTMLImageElement, name: string, value: string) {
    return setAttribute.call(this, name, name === "src" ? rewrite(value) : value);
  };
  const descriptor = Object.getOwnPropertyDescriptor(proto, "src");
  if (descriptor?.set) {
    const set = descriptor.set;
    Object.defineProperty(proto, "src", { ...descriptor, set(this: HTMLImageElement, value: string) { set.call(this, rewrite(value)); } });
  }
}

/** Story decorator: serves the `pic-*` fixture files as pictures. */
export const withPictureFiles: Decorator = (Story) => {
  installRewrite();
  return <Story />;
};
