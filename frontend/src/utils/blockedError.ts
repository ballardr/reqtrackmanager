/**
 * Module: utils/blockedError
 *
 * Turns a "still in use" conflict from a delete into a plain error with a message an administrator can act on,
 * for the vocabulary lists that block deleting a value a record still uses (the shared `DefinitionList` would otherwise
 * offer a reassignment these lists do not support).
 */
import { ApiError } from "../api/client";

/**
 * Re-throws a 409 as a plain `Error` carrying `message`, keeping the cause as a property (`{ cause }` predates this
 * project's `lib` target).
 *
 * @param err The error a delete threw.
 * @param message What to tell the administrator when it was a 409.
 * @returns A plain `Error` carrying `message` (the cause kept) for a 409; `err` unchanged otherwise.
 */
export function blockedError(err: unknown, message: string): unknown {
  if (err instanceof ApiError && err.status === 409) {
    const wrapped = new Error(message) as Error & { cause?: unknown };
    wrapped.cause = err;
    return wrapped;
  }
  return err;
}
