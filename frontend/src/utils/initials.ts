/**
 * Module: utils/initials
 *
 * The initials of a person's display name, for a small round marker (a comment pin).
 */

/**
 * @param name A display name; may be blank.
 * @returns Up to two upper-case letters: the first letters of the first and last words, or the first two letters of a single
 *   word; `?` for a blank name.
 */
export function initialsOf(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "?";
  return (words.length === 1 ? words[0].slice(0, 2) : words[0][0] + words[words.length - 1][0]).toUpperCase();
}
