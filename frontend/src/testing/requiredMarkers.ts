/**
 * Module: testing/requiredMarkers
 *
 * The shared "which fields does this form mark required?" assertion (docs/ux-style-guide.md, "Pattern:
 * required fields"). A form marks exactly the fields it blocks on with a `*` after the caption, and an
 * unmarked field is optional. A story reads the marked captions here and compares them with the fields the
 * form really blocks on, so a star and the validation cannot drift apart.
 */

/**
 * The captions of every field under `root` that carries a required mark, in document order, without the `*`.
 *
 * @param root The element holding the form (a dialog, or the story canvas).
 * @returns The caption text of each marked field.
 */
export function requiredCaptions(root: ParentNode): string[] {
  return Array.from(root.querySelectorAll(".field-required")).map((mark) => {
    const caption = mark.parentElement;
    return (caption?.textContent ?? "").trim();
  });
}

/**
 * The controls under `root` the browser treats as required (`required` or `aria-required`), by their
 * accessible name, so a story can check the star and the native constraint agree.
 *
 * @param root The element holding the form.
 * @returns The `aria-label` (else the id) of each required control.
 */
export function requiredControlNames(root: ParentNode): string[] {
  return Array.from(root.querySelectorAll<HTMLElement>("[required], [aria-required='true']")).map(
    (el) => el.getAttribute("aria-label") ?? el.id,
  );
}
