import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Linking } from 'react-native';
import {
  createQuote,
  getOrder,
  getPaymentMethods,
  listMarkets,
  listProducts,
  placeCheckout,
  type MarketSummary,
  type OrderResponse,
  type PaymentMethodsResponse,
  type ProductSummary,
  type QuoteResponse,
} from '../../api/checkoutClient';
import { ApiError } from '../../api/http';
import {
  clearPendingOrder,
  loadPendingOrder,
  markPaymentStarted,
  savePendingOrder,
} from '../../services/pendingOrder';
import {
  checkDevice,
  confirmedByCustomer,
  UNCHECKED,
  type DeviceCheck,
} from './deviceFacts';
import { OrderStatusScreen, headlineFor } from './OrderStatusScreen';
import { PlanListScreen } from './PlanListScreen';
import { QuoteReviewScreen } from './QuoteReviewScreen';

/**
 * Browse → quote → pay → recover, as one flow (US-37, chunk 19).
 *
 * The three screens are deliberately dumb; every decision that could cost a
 * customer money is here, and there are only three of them.
 *
 * **1. Recovery comes before browsing.** On mount the flow reads the persisted
 * order *first*, and if there is one it opens the order rather than the catalog.
 * This is the whole of AC-37.5: the customer who paid and whose app was killed
 * must find their order, and the surest way to sell somebody the same eSIM twice
 * is to greet them with a plan list.
 *
 * **2. A retry is the same call, not a new one.** Paying, resuming after a
 * decline and returning from a lost redirect are all `POST /checkout` with the
 * same quote id. The server treats the quote as the idempotency key, so the
 * second call returns the first order with `resumed: true`. Nothing here
 * generates a fresh key on retry, which is what would let the two disagree.
 *
 * **3. The order is written to disk before the customer leaves.** Not after the
 * redirect resolves — there may be no "after" if the OS reclaims the app while
 * the processor has the screen.
 */

type Stage = 'browse' | 'review' | 'order';

interface PurchaseFlowProps {
  accessToken: string;
  /** An order to open directly — from Home, or from an `damdam://orders/:id` link. */
  initialOrderId?: string | null;
  /** Called once the requested order has been opened, so it is not reopened. */
  onOrderOpened?: () => void;
  /** Something changed that Home's service list should re-read. */
  onPurchaseSettled?: () => void;
  onOpenMyLine: () => void;
}

export function PurchaseFlow({
  accessToken,
  initialOrderId = null,
  onOrderOpened,
  onPurchaseSettled,
  onOpenMyLine,
}: PurchaseFlowProps): React.JSX.Element {
  const [stage, setStage] = useState<Stage>('browse');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const [markets, setMarkets] = useState<MarketSummary[]>([]);
  const [market, setMarket] = useState<MarketSummary | null>(null);
  const [products, setProducts] = useState<ProductSummary[]>([]);
  const [device, setDevice] = useState<DeviceCheck>(UNCHECKED);

  const [quote, setQuote] = useState<QuoteResponse | null>(null);
  const [quoteRejected, setQuoteRejected] = useState(false);
  const [methods, setMethods] = useState<PaymentMethodsResponse | null>(null);
  const [chosenProduct, setChosenProduct] = useState<ProductSummary | null>(null);
  const [busyProductId, setBusyProductId] = useState<string | null>(null);

  const [order, setOrder] = useState<OrderResponse | null>(null);
  const [orderId, setOrderId] = useState<string | null>(null);
  const [orderReference, setOrderReference] = useState('');
  const [paymentStarted, setPaymentStarted] = useState(false);
  const [quoteIdForOrder, setQuoteIdForOrder] = useState<string | null>(null);

  /**
   * Guards the pay button against the second press that arrives before React
   * has re-rendered with `busy`. A ref rather than state because the check and
   * the set have to happen in the same tick — `busy` would still be false when
   * the second handler reads it.
   */
  const paying = useRef(false);

  const describe = useCallback((error: unknown): string => {
    return error instanceof ApiError ? error.message : String(error);
  }, []);

  // --- browsing ------------------------------------------------------------

  const loadCatalog = useCallback(
    async (facts: DeviceCheck, chosenMarket?: MarketSummary) => {
      setLoading(true);
      setErrorMessage(null);
      try {
        const { markets: available } = await listMarkets();
        setMarkets(available);
        const target = chosenMarket ?? available[0] ?? null;
        setMarket(target);
        if (!target) {
          setProducts([]);
          return;
        }
        const listing = await listProducts(
          target.country,
          target.currency,
          facts.facts,
        );
        setProducts(listing.products);
      } catch (error) {
        setErrorMessage(describe(error));
      } finally {
        setLoading(false);
      }
    },
    [describe],
  );

  // --- opening an order ----------------------------------------------------

  const openOrder = useCallback(
    async (id: string, options: { started?: boolean; reference?: string } = {}) => {
      setStage('order');
      setOrderId(id);
      if (options.reference !== undefined) {
        setOrderReference(options.reference);
      }
      if (options.started !== undefined) {
        setPaymentStarted(options.started);
      }
      setLoading(true);
      setErrorMessage(null);
      try {
        const fetched = await getOrder(accessToken, id);
        setOrder(fetched);
        setOrderReference(fetched.reference);
        // A settled order should not force the status screen onto the next cold
        // start. The record is dropped now; the screen itself stays until the
        // customer dismisses it, because it is their confirmation.
        const headline = headlineFor(fetched, options.started ?? paymentStarted);
        if (headline === 'ready' || headline === 'refunded') {
          await clearPendingOrder();
        }
      } catch (error) {
        setErrorMessage(describe(error));
      } finally {
        setLoading(false);
      }
    },
    [accessToken, describe, paymentStarted],
  );

  // --- first paint ---------------------------------------------------------

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const facts = await checkDevice();
      if (cancelled) {
        return;
      }
      setDevice(facts);

      if (initialOrderId) {
        // The order-opening effect below owns this start. Reading the persisted
        // record here too would race it and could open the wrong order.
        return;
      }

      const pending = await loadPendingOrder();
      if (cancelled) {
        return;
      }
      if (pending) {
        setQuoteIdForOrder(pending.quoteId);
        await openOrder(pending.orderId, {
          started: pending.paymentStarted,
          reference: pending.reference,
        });
        return;
      }
      await loadCatalog(facts);
    })();
    return () => {
      cancelled = true;
    };
    // Deliberately once: this is the cold-start decision, and re-running it
    // would drag a customer mid-review back to whatever is on disk.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!initialOrderId) {
      return;
    }
    openOrder(initialOrderId);
    onOrderOpened?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialOrderId]);

  // --- choosing ------------------------------------------------------------

  const choose = useCallback(
    async (product: ProductSummary) => {
      if (!market || busyProductId) {
        return;
      }
      setBusyProductId(product.product_id);
      setErrorMessage(null);
      try {
        const issued = await createQuote(accessToken, {
          country: market.country,
          currency: market.currency,
          lines: [{ product_id: product.product_id, quantity: 1 }],
          device: device.facts,
        });
        setQuote(issued);
        setQuoteRejected(false);
        setChosenProduct(product);
        setStage('review');
        // Best effort: a review screen that cannot say which wallets are
        // offered is still a usable review screen, and failing the whole
        // quote over it would be worse.
        getPaymentMethods(accessToken, {
          country: market.country,
          currency: market.currency,
        })
          .then(setMethods)
          .catch(() => setMethods(null));
      } catch (error) {
        setErrorMessage(describe(error));
      } finally {
        setBusyProductId(null);
      }
    },
    [accessToken, busyProductId, describe, device.facts, market],
  );

  const requote = useCallback(async () => {
    if (!chosenProduct) {
      setStage('browse');
      return;
    }
    setQuote(null);
    setQuoteRejected(false);
    setStage('browse');
    await choose(chosenProduct);
  }, [chosenProduct, choose]);

  // --- paying --------------------------------------------------------------

  const pay = useCallback(
    async (quoteId: string) => {
      if (paying.current) {
        return;
      }
      paying.current = true;
      setBusy(true);
      setErrorMessage(null);
      try {
        const result = await placeCheckout(accessToken, quoteId);
        setOrder(result.order);
        setOrderId(result.order.order_id);
        setOrderReference(result.order.reference);
        setQuoteIdForOrder(quoteId);

        const started = result.outcome === 'pay' && result.redirect_url !== null;
        // Written before the redirect, never after: the app may not be alive
        // when the processor hands the screen back.
        await savePendingOrder({
          orderId: result.order.order_id,
          quoteId,
          reference: result.order.reference,
          paymentStarted: started,
        });
        setPaymentStarted(started);
        setStage('order');

        if (started && result.redirect_url) {
          await markPaymentStarted();
          // The URL is opened and deliberately not kept. See pendingOrder.ts:
          // it is a payment capability, and AsyncStorage is not the place for
          // one.
          Linking.openURL(result.redirect_url).catch(() => undefined);
        }
        onPurchaseSettled?.();
      } catch (error) {
        if (error instanceof ApiError && isQuoteRefusal(error.code)) {
          // The basket is fine; the price is stale or spent. Re-pricing is the
          // route forward, and it is not a failure worth an error banner.
          setQuoteRejected(true);
          setStage('review');
        } else {
          setErrorMessage(describe(error));
        }
      } finally {
        paying.current = false;
        setBusy(false);
      }
    },
    [accessToken, describe, onPurchaseSettled],
  );

  // --- order actions -------------------------------------------------------

  const refresh = useCallback(async () => {
    if (!orderId) {
      return;
    }
    await openOrder(orderId);
    onPurchaseSettled?.();
  }, [onPurchaseSettled, openOrder, orderId]);

  const dismiss = useCallback(async () => {
    await clearPendingOrder();
    setOrder(null);
    setOrderId(null);
    setOrderReference('');
    setQuote(null);
    setChosenProduct(null);
    setQuoteIdForOrder(null);
    setPaymentStarted(false);
    setStage('browse');
    await loadCatalog(device);
  }, [device, loadCatalog]);

  const confirmEsimCapable = useCallback(async () => {
    const next = confirmedByCustomer(device);
    setDevice(next);
    await loadCatalog(next, market ?? undefined);
  }, [device, loadCatalog, market]);

  const selectMarket = useCallback(
    async (next: MarketSummary) => {
      setMarket(next);
      await loadCatalog(device, next);
    },
    [device, loadCatalog],
  );

  // --- render --------------------------------------------------------------

  if (stage === 'order') {
    return (
      <OrderStatusScreen
        order={order}
        reference={orderReference}
        paymentStarted={paymentStarted}
        loading={loading}
        busy={busy}
        errorMessage={errorMessage}
        onRefresh={refresh}
        onResumePayment={() => quoteIdForOrder && pay(quoteIdForOrder)}
        onOpenMyLine={onOpenMyLine}
        onBrowsePlans={dismiss}
        onDismiss={dismiss}
      />
    );
  }

  if (stage === 'review' && quote) {
    return (
      <QuoteReviewScreen
        quote={quote}
        methods={methods}
        paying={busy}
        errorMessage={errorMessage}
        quoteRejected={quoteRejected}
        onPay={() => pay(quote.quote_id)}
        onRequote={requote}
        onBack={() => {
          setStage('browse');
          setErrorMessage(null);
        }}
      />
    );
  }

  return (
    <PlanListScreen
      markets={markets}
      market={market}
      products={products}
      device={device}
      loading={loading}
      errorMessage={errorMessage}
      busyProductId={busyProductId}
      onSelectMarket={selectMarket}
      onChoose={choose}
      onConfirmEsimCapable={confirmEsimCapable}
      onRetry={() => loadCatalog(device, market ?? undefined)}
    />
  );
}

/**
 * Errors that mean "this price is no longer usable", as opposed to "something
 * went wrong".
 *
 * They share one route out — get a fresh quote — and none of them is the
 * customer's mistake, so none of them should read as an error. `quote_tampered`
 * is included because whatever caused it, the customer's next step is identical
 * and a security phrasing at a payment screen helps nobody.
 */
function isQuoteRefusal(code: string): boolean {
  return [
    'quote_expired',
    'quote_void',
    'quote_not_found',
    'quote_tampered',
    // Redeemed with no order behind it — a checkout that died between claiming
    // the price and creating the order. The price is spent either way.
    'quote_already_redeemed',
  ].includes(code);
}
