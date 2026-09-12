import { checkEsimCompatibility } from '../../utils/esimCompatibility';
import type { DeviceFactsRequest } from '../../api/checkoutClient';

/**
 * What this phone can be *observed* to do, and who observed it (US-37, chunk 19).
 *
 * The chunk is explicit: give practical guidance where automatic device and
 * carrier-lock detection is unavailable, and **do not imply guaranteed
 * detection**. Two facts, two very different confidence levels:
 *
 * | Fact | Source | Confidence |
 * |---|---|---|
 * | eSIM capability | `EuiccManager.isEnabled()` on Android; a model-generation heuristic on iOS, which has no capability API | high / indicative |
 * | Carrier lock | nothing — neither platform exposes it | none, ever |
 *
 * `is_unlocked` is therefore `null` permanently. It is not a field waiting on a
 * better API; it is a fact the app is not entitled to assert. The server only
 * refuses on an explicit `false`, so leaving it unanswered keeps the plan
 * buyable and puts the question in front of the customer as guidance — which is
 * the only place it can honestly be answered.
 *
 * ## Why the customer can overrule the eSIM check
 *
 * On iOS the check is a heuristic over the hardware identifier and it is
 * deliberately conservative: anything it does not recognize — a simulator, a
 * model newer than the pattern — comes back unsupported. Conservative is right
 * for a warning and wrong as a verdict, because a customer holding a capable
 * phone the heuristic missed would be locked out of every eSIM plan with no way
 * past it.
 *
 * So a negative result is shown with the two checks a person can actually
 * perform (an EID in the phone's own settings, or `*#06#`), and confirming what
 * they find sets the fact to true. That is not the app claiming detection it
 * does not have; it is the app reporting an observation somebody made, and
 * `source` keeps the difference legible to anyone reading a quote later.
 */

export type FactSource = 'unchecked' | 'device' | 'customer';

export interface DeviceCheck {
  facts: DeviceFactsRequest;
  source: FactSource;
  /** Null until the check has run. */
  model: string | null;
  /** True once the automatic check has run and come back negative. */
  reportedIncapable: boolean;
}

export const UNCHECKED: DeviceCheck = {
  facts: { supports_esim: null, is_unlocked: null },
  source: 'unchecked',
  model: null,
  reportedIncapable: false,
};

export async function checkDevice(): Promise<DeviceCheck> {
  try {
    const result = await checkEsimCompatibility();
    return {
      facts: { supports_esim: result.supported, is_unlocked: null },
      source: 'device',
      model: result.deviceModel,
      reportedIncapable: !result.supported,
    };
  } catch {
    // A check that could not run is "not checked", never "incapable". The
    // customer keeps the plans and gets the guidance.
    return UNCHECKED;
  }
}

/**
 * The customer looked, and their phone has an EID.
 *
 * Kept as a separate constructor rather than a `setSupportsEsim(true)` so the
 * provenance survives: `source: 'customer'` is the difference between a
 * capability the device reported and one a person read off a settings screen,
 * and only the second one can be wrong in the customer's favour.
 */
export function confirmedByCustomer(check: DeviceCheck): DeviceCheck {
  return {
    facts: { supports_esim: true, is_unlocked: null },
    source: 'customer',
    model: check.model,
    reportedIncapable: false,
  };
}
