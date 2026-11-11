/**
 * Module: context/brandingEvents
 *
 * The window event that tells `BrandingProvider` to read the deployment-wide settings it serves again. It is
 * dispatched after a server administrator changes one (the file upload switch), so the open page does not wait
 * for the next navigation into a project space. Kept apart from the provider so the provider file exports only
 * components and hooks.
 */

/** Dispatched on `window` after a deployment-wide setting served by `BrandingProvider` changes. */
export const BRANDING_CHANGED_EVENT = "reqtrack:branding-changed";
