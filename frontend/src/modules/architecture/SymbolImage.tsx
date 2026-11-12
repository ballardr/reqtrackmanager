/**
 * Module: modules/architecture/SymbolImage
 *
 * Draws one symbol from the library. The API needs the person's token, which an `<img src>` cannot send, so the
 * sanitised SVG is fetched with the shared client and shown from an object URL; an `<img>` never runs a script, which is
 * a second guard after the server-side sanitising. Shows nothing while loading and a muted dash when the file cannot be
 * read (the symbol was removed or is not visible to the viewer).
 */
import { useEffect, useState } from "react";

import { api } from "../../api/client";

/**
 * @param src The API path of the symbol's content (`projectSymbolUrl` / `orgSymbolUrl`); `null` draws nothing.
 * @param alt The image's text alternative (the symbol's name).
 * @param size The width and height in pixels.
 */
export function SymbolImage({ src, alt, size = 28 }: { src: string | null; alt: string; size?: number }) {
  // The outcome is keyed by the path it answers, so a stale reply is never shown for a newer `src`.
  const [loaded, setLoaded] = useState<{ src: string; url: string | null } | null>(null);

  useEffect(() => {
    if (!src) return;
    let live = true;
    let objectUrl: string | null = null;
    api.getForBlob(src)
      .then((blob) => {
        if (!live) return;
        objectUrl = URL.createObjectURL(blob);
        setLoaded({ src, url: objectUrl });
      })
      .catch(() => { if (live) setLoaded({ src, url: null }); });
    return () => {
      live = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [src]);

  if (!src) return null;
  const outcome = loaded?.src === src ? loaded : null;
  if (outcome && outcome.url === null) return <span className="text-muted" aria-label={`${alt} unavailable`}>—</span>;
  if (!outcome || !outcome.url) return <span style={{ display: "inline-block", width: size, height: size }} aria-hidden="true" />;
  return <img src={outcome.url} alt={alt} width={size} height={size} style={{ objectFit: "contain" }} />;
}
