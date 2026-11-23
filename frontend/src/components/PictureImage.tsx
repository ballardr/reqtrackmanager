/**
 * Module: components/PictureImage
 *
 * Draws an uploaded picture (a report image, an organisation logo) on a backdrop that keeps transparent and
 * single-colour pictures visible, and the switch that chooses the backdrop.
 *
 * - `PictureImage`: an `<img>` with the shared `.picture-backdrop` class, so every library picture looks the same.
 * - `PictureBackdropSwitch`: checkerboard, light or dark, for judging a logo against the page it will print on.
 *
 * The default is a checkerboard (the convention for transparency, independent of the picture's pixels), built from
 * two theme tokens so it reads in light and dark. The choice is one per-person preference (`usePictureBackdrop`)
 * read by every `PictureImage`, so a switch in one place applies everywhere.
 */
import type { ImgHTMLAttributes } from "react";

import { useStrings } from "../context/TerminologyContext";
import { PICTURE_BACKDROPS, usePictureBackdrop } from "../hooks/usePictureBackdrop";

/**
 * An image drawn on the person's chosen backdrop.
 *
 * Args:
 *   src, className, ...: ordinary `<img>` attributes; `className` is added to the shared backdrop class and `alt`
 *     defaults to empty (a decorative picture beside its own name).
 */
export function PictureImage({ className, alt = "", ...rest }: ImgHTMLAttributes<HTMLImageElement>) {
  const [backdrop] = usePictureBackdrop();
  return <img {...rest} alt={alt} className={className ? `picture-backdrop ${className}` : "picture-backdrop"} data-backdrop={backdrop} />;
}

/** Three buttons (checkerboard, light, dark) choosing the backdrop every `PictureImage` is drawn on. */
export function PictureBackdropSwitch() {
  const text = useStrings().reportImages.backdrop;
  const [backdrop, setBackdrop] = usePictureBackdrop();
  return (
    <div className="row" role="group" aria-label={text.label} style={{ gap: "var(--space-1)", flexWrap: "wrap" }}>
      <span className="text-muted" style={{ fontSize: "0.8rem" }}>{text.label}</span>
      {PICTURE_BACKDROPS.map((option) => (
        <button
          key={option} type="button" className={`btn btn-sm ${backdrop === option ? "btn-primary" : ""}`}
          aria-pressed={backdrop === option} onClick={() => setBackdrop(option)}
        >
          {text.options[option]}
        </button>
      ))}
    </div>
  );
}
