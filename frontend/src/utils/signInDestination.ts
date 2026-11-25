/**
 * Module: utils/signInDestination
 *
 * Decides which page a person is sent to once they are signed in.
 *
 * Responsibilities: the page they were on when sign-in was required (`utils/returnTo`), otherwise their landing
 * preference (a project, the project list, or the only project they can open).
 *
 * External dependencies: the projects API, for the automatic landing preference.
 */
import { api } from "../api/client";
import type { ProjectListItem, User } from "../api/types";
import { takeReturnTo } from "./returnTo";

/**
 * Resolves where to send the user after login (U-U-03): a specific project,
 * the project overview list, or "automatic" (the sole accessible project if
 * there's exactly one, else the overview list).
 */
export async function resolveLandingPath(user: User): Promise<string> {
  const preference = user.landing_preference;
  if (preference && preference !== "auto" && preference !== "overview") {
    return `/projects/${preference}`;
  }
  if (preference === "overview") {
    return "/projects";
  }
  const projects = await api.get<ProjectListItem[]>("/api/v1/projects?archived=false");
  return projects.length === 1 ? `/projects/${projects[0].id}` : "/projects";
}

/**
 * Resolves where to send the person once they are signed in: the page they were on when they were sent to sign in
 * (used once, see `utils/returnTo`), otherwise their landing preference.
 */
export async function resolvePostSignInPath(user: User): Promise<string> {
  return takeReturnTo() ?? (await resolveLandingPath(user));
}
