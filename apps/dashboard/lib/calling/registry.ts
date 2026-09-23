import { UnavailableCallAdapter, type CallClientAdapter } from "./adapter";

/**
 * Which browser calling adapter this build has. Today: none.
 *
 * Installing `@telnyx/webrtc` is a change to this file plus one new adapter
 * module — nothing in the controller, the page or the tests moves. That is
 * what the boundary is for.
 *
 * It is not installed because D1 is open: there is no Telnyx account, so there
 * are no credentials to connect with and nothing that could be proven by adding
 * the dependency. V01 established the browser client from documentation only
 * and recorded the exact browser/version matrix as UNKNOWN.
 */
export function resolveCallAdapter(): CallClientAdapter {
  return new UnavailableCallAdapter();
}
