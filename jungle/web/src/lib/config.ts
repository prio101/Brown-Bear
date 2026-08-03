/**
 * Server-side configuration.
 *
 * BB_API_URL points at the FastAPI app by its compose service name, which only
 * resolves inside the Docker network. That is deliberate: data fetching happens
 * server-side, so no API credential ever reaches the browser (sprint-1 D1).
 */

export const APP_NAME = "Brown Bear";

/** The FastAPI app. Reachable by service name on the compose network. */
export const API_URL = process.env.BB_API_URL ?? "http://app:8080";
