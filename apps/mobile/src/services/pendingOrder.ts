import AsyncStorage from '@react-native-async-storage/async-storage';

/**
 * The order the app must come back to (US-37 AC-37.5, chunk 19).
 *
 * The failure this exists for is ordinary and expensive: the customer taps pay,
 * the OS opens the processor, the app is evicted while it is in the background,
 * and the customer returns to a cold start. Without a record on disk the app
 * knows nothing about the money that just moved, shows an empty Plans tab, and
 * the only affordance in front of somebody who has already paid is *buy again*.
 *
 * So the identity of the purchase is written down **before** the customer
 * leaves, and the record is cleared only when the order is finished — paid and
 * provisioned — or explicitly abandoned.
 *
 * ## What is deliberately not stored
 *
 * The processor's `redirect_url`. It is a capability: whoever holds it can open
 * that payment session, and it commonly carries a session token in the query
 * string. AsyncStorage is unencrypted (that is why `sessionStore` uses the
 * Keychain instead), and a payment link surviving on disk after the payment is a
 * credential nobody is watching. The order id is enough to recover: asking the
 * server "what happened to this order" produces a fresh session if one is still
 * needed, and the truth if one is not.
 *
 * Card numbers, wallet tokens and anything else the customer typed into the
 * processor never reach the app at all, by construction — the hosted checkout
 * collects them.
 */

export const PENDING_ORDER_KEY = 'damdam.pendingOrder.v1';

export interface PendingOrder {
  orderId: string;
  /**
   * The quote this order was placed from. Kept because a resumed checkout is
   * `POST /checkout` with the *same* quote id — that is what returns the
   * existing order instead of creating a second one — and after a restart the
   * app has no other way to name it.
   */
  quoteId: string;
  /** Shown while the order itself is still loading, so the screen is never blank. */
  reference: string;
  /**
   * True once the customer has actually been sent to the processor.
   *
   * This is local knowledge and it changes what the app may say. An `unpaid`
   * order the customer never tried to pay is "you haven't paid yet"; an
   * `unpaid` order they were sent to the processor for is "we're confirming
   * your payment" — the delayed-webhook case — and telling those two apart
   * wrongly either nags somebody who has paid or reassures somebody who has not.
   */
  paymentStarted: boolean;
  savedAt: string;
}

interface StoredOrder extends Omit<PendingOrder, 'savedAt'> {
  savedAt?: string;
}

export async function savePendingOrder(
  order: Omit<PendingOrder, 'savedAt'>,
): Promise<PendingOrder> {
  const record: PendingOrder = { ...order, savedAt: new Date().toISOString() };
  await AsyncStorage.setItem(PENDING_ORDER_KEY, JSON.stringify(record));
  return record;
}

export async function loadPendingOrder(): Promise<PendingOrder | null> {
  try {
    const raw = await AsyncStorage.getItem(PENDING_ORDER_KEY);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as StoredOrder;
    if (!parsed.orderId || !parsed.quoteId) {
      // A record that cannot name an order cannot recover one. Dropping it is
      // better than carrying a half-written row that makes every start show an
      // order screen with nothing behind it.
      return null;
    }
    return {
      orderId: parsed.orderId,
      quoteId: parsed.quoteId,
      reference: parsed.reference ?? '',
      paymentStarted: parsed.paymentStarted === true,
      savedAt: parsed.savedAt ?? new Date().toISOString(),
    };
  } catch {
    return null;
  }
}

/** Called when the customer is sent to the processor, before the app loses focus. */
export async function markPaymentStarted(): Promise<PendingOrder | null> {
  const current = await loadPendingOrder();
  if (!current) {
    return null;
  }
  return savePendingOrder({ ...current, paymentStarted: true });
}

export async function clearPendingOrder(): Promise<void> {
  try {
    await AsyncStorage.removeItem(PENDING_ORDER_KEY);
  } catch {
    // A record that outlives its order is recoverable — the app reloads it and
    // finds a finished order. Throwing here would fail a purchase that
    // succeeded.
  }
}
