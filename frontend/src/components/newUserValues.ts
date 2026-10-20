/** The values of the shared `NewUserFields` form, and an empty starting set. */
import type { OrgRole } from "../api/types";

export interface NewUserValues {
  email: string;
  displayName: string;
  password: string;
  role: OrgRole;
}

export const EMPTY_NEW_USER: NewUserValues = { email: "", displayName: "", password: "", role: "member" };
