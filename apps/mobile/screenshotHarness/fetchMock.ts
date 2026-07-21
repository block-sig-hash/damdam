/**
 * Replaces global.fetch with a canned-response router for the handful
 * of endpoints the screenshot harness's target screens call on mount.
 * Only ever installed from ScreenshotHarnessApp -- never touches a
 * production build, since that entry point is only reachable when
 * SCREENSHOT_HARNESS_MODE is inlined true at build time.
 */
import {
  FIXTURE_ACTIVATION_REDEMPTION,
  FIXTURE_CALL_HISTORY,
  FIXTURE_ESIM_PROFILE,
  FIXTURE_PRICING_TIERS,
} from './fixtures';

function jsonResponse(body: unknown, status = 200): Response {
  // Do not depend on a browser `Response` constructor in the React Native
  // device runtime. The application clients only consume this small response
  // surface, so a deterministic test double is sufficient for the harness.
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as Response;
}

type Route = {
  method: string;
  match: (path: string) => boolean;
  respond: () => Response;
};

const routes: Route[] = [
  {
    method: 'GET',
    match: (path) => path.endsWith('/pricing/tiers'),
    respond: () => jsonResponse({ tiers: FIXTURE_PRICING_TIERS }),
  },
  {
    method: 'POST',
    match: (path) => /\/packages\/[^/]+\/esim\/issue$/.test(path),
    respond: () => jsonResponse(FIXTURE_ESIM_PROFILE),
  },
  {
    method: 'GET',
    match: (path) => /\/packages\/[^/]+\/esim$/.test(path),
    respond: () => jsonResponse(FIXTURE_ESIM_PROFILE),
  },
  {
    method: 'POST',
    match: (path) => path.endsWith('/me/activation/redeem'),
    respond: () => jsonResponse(FIXTURE_ACTIVATION_REDEMPTION),
  },
  {
    method: 'GET',
    match: (path) => path.includes('/me/calls'),
    respond: () => jsonResponse({ calls: FIXTURE_CALL_HISTORY }),
  },
];

let installed = false;

export function installHarnessFetchMock(): void {
  if (installed) return;
  installed = true;

  global.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString();
    const path = url.split('?')[0];
    const method = (init?.method ?? 'GET').toUpperCase();

    const route = routes.find((candidate) => candidate.method === method && candidate.match(path));
    if (route) {
      return route.respond();
    }

    // Unrecognized request from a harness target: fail loudly with a 404
    // rather than hang, so a missing fixture shows up as an on-screen
    // error state instead of an indefinite spinner.
    return jsonResponse({ message: `No harness fixture for ${method} ${path}` }, 404);
  }) as typeof fetch;
}
