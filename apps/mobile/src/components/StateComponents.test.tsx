/**
 * The state components, tested for the things that make them worth having.
 *
 * Not "does it render the string I passed in" — that tests React. What is
 * tested here is the behaviour a later screen chunk could quietly break:
 * a usage meter that paints a full bar when nothing has been reported, a pill
 * that announces a bare state name with no idea which question it answers, a
 * partial failure that stops telling people a retry is free.
 */

import React from 'react';
import { render, screen } from '@testing-library/react-native';

import { announce } from './announce';
import { PartialFailureNotice } from './PartialFailureNotice/PartialFailureNotice';
import { StateMessage } from './StateMessage/StateMessage';
import { StatusPill } from './StatusPill/StatusPill';
import { UsageMeter } from './UsageMeter/UsageMeter';
import { color } from '../theme/tokens';

const flatten = (style: unknown): Record<string, unknown> =>
  Object.assign({}, ...[style].flat(Infinity).filter(Boolean));

describe('StatusPill', () => {
  it('announces which question it answers, not just the answer', async () => {
    // Four pills can sit on one card. "Not connected" alone is meaningless to
    // someone listening rather than looking.
    await render(
      <StatusPill family="Network" label="Not connected" tone="caution" testID="pill" />,
    );
    expect(screen.getByTestId('pill').props.accessibilityLabel).toBe('Network: Not connected');
  });

  it('never renders a saturated fill with white text', async () => {
    // design-system.md §1: at pill size a light tint is the only pairing that
    // holds AA across every semantic colour at once.
    const tints = [color.gray100, color.info100, color.success100, color.warning100, color.error100];
    for (const tone of ['neutral', 'progress', 'positive', 'caution', 'negative'] as const) {
      await render(
        <StatusPill family="Payment" label="x" tone={tone} testID={`pill-${tone}`} />,
      );
      expect(tints).toContain(flatten(screen.getByTestId(`pill-${tone}`).props.style).backgroundColor);
    }
  });

  it('lets a long label wrap rather than clipping it to one line', async () => {
    // "Vérification auprès du réseau" is more than double its English source.
    await render(
      <StatusPill
        family="Configuration"
        label="Vérification auprès du réseau"
        tone="progress"
      />,
    );
    expect(screen.getByText('Vérification auprès du réseau').props.numberOfLines).toBe(2);
  });
});

describe('UsageMeter', () => {
  it('shows an empty grey bar when the network has never reported', async () => {
    // A full green bar here would be an invented reading, and someone would
    // plan a journey around it.
    await render(
      <UsageMeter
        label="Data"
        remaining="—"
        total="10 GB"
        fraction={0}
        updatedLabel={null}
        testID="meter"
      />,
    );
    const fill = flatten(screen.getByTestId('meter-track').props.children.props.style);
    expect(fill.backgroundColor).toBe(color.gray300);
    expect(fill.width).toBe('0%');
  });

  it('colours the fill by how much is left, on the banner thresholds', async () => {
    const cases: [number, string][] = [
      [0.8, color.success500],
      [0.1, color.warning500],
      [0.02, color.error700],
    ];
    for (const [fraction, expected] of cases) {
      await render(
        <UsageMeter
          label="Data"
          remaining="x"
          total="y"
          fraction={fraction}
          updatedLabel="Updated 2 minutes ago"
          testID={`meter-${fraction}`}
        />,
      );
      const fill = flatten(screen.getByTestId(`meter-${fraction}-track`).props.children.props.style);
      expect(fill.backgroundColor).toBe(expected);
    }
  });

  it('clamps a supplier over-report instead of overflowing the bar', async () => {
    await render(
      <UsageMeter
        label="Data"
        remaining="x"
        total="y"
        fraction={1.4}
        updatedLabel="Updated"
        testID="meter"
      />,
    );
    expect(flatten(screen.getByTestId('meter-track').props.children.props.style).width).toBe('100%');
  });

  it('survives a non-finite fraction rather than rendering NaN%', async () => {
    await render(
      <UsageMeter
        label="Data"
        remaining="x"
        total="y"
        fraction={Number.NaN}
        updatedLabel="Updated"
        testID="meter"
      />,
    );
    expect(flatten(screen.getByTestId('meter-track').props.children.props.style).width).toBe('0%');
  });

  it('always shows how old the reading is', async () => {
    await render(
      <UsageMeter
        label="Data"
        remaining="4.2 GB"
        total="10 GB"
        fraction={0.42}
        updatedLabel="Last updated 3 hours ago"
        stale
        explanation="Usage can take a little while to reach us."
        testID="meter"
      />,
    );
    expect(screen.getByTestId('meter-updated').props.children).toBe('Last updated 3 hours ago');
    expect(screen.getByTestId('meter-explanation')).toBeTruthy();
  });

  it('does not colour a late reading as an alert', async () => {
    // A late reading is normal. Painting it red trains people to ignore red.
    await render(
      <UsageMeter
        label="Data"
        remaining="x"
        total="y"
        fraction={0.5}
        updatedLabel="Last updated 3 hours ago"
        stale
        testID="meter"
      />,
    );
    const style = flatten(screen.getByTestId('meter-updated').props.style);
    expect([color.error700, color.warning500, color.warning700]).not.toContain(style.color);
  });

  it('reports its value to assistive technology as a percentage', async () => {
    await render(
      <UsageMeter
        label="Data"
        remaining="4.2 GB"
        total="10 GB"
        fraction={0.42}
        updatedLabel="Updated"
        testID="meter"
      />,
    );
    expect(screen.getByTestId('meter-track').props.accessibilityValue).toEqual({
      min: 0,
      max: 100,
      now: 42,
    });
  });
});

describe('StateMessage', () => {
  it('does not dress an empty list up as a problem', async () => {
    await render(
      <StateMessage
        variant="empty"
        title="No lines yet"
        body="Lines you buy will appear here."
        testID="state"
      />,
    );
    const style = flatten(screen.getByTestId('state').props.style);
    expect(style.backgroundColor).toBe(color.gray50);
    expect(style.borderColor).toBe(color.gray200);
  });

  it('reads as one sentence to a screen reader', async () => {
    await render(
      <StateMessage
        variant="pending"
        title="Your line is being set up"
        body="We have your payment."
        footnote="You do not need to wait here."
        testID="state"
      />,
    );
    expect(screen.getByTestId('state-summary').props.accessibilityLabel).toBe(
      'Your line is being set up. We have your payment. You do not need to wait here.',
    );
  });

  it('disables the action while a retry is in flight', async () => {
    // Otherwise an impatient second tap sends a second request.
    await render(
      <StateMessage
        variant="error"
        title="That did not work"
        body="Nothing was charged."
        actionLabel="Try again"
        busyLabel="Trying again…"
        busy
        onAction={() => undefined}
        testID="state"
      />,
    );
    const action = screen.getByTestId('state-action');
    expect(action.props.accessibilityState.disabled).toBe(true);
    expect(screen.getByTestId('state').props.accessible).not.toBe(true);
    expect(screen.getByTestId('state-summary').props.accessible).toBe(true);
  });

  it('distinguishes blocked from failed', async () => {
    // "Your phone cannot use an eSIM" is not an error the app can retry out
    // of, and rendering it in the same red as a failed payment invites people
    // to keep trying something that will never work.
    await render(
      <>
        <StateMessage variant="blocked" title="a" body="b" testID="blocked" />
        <StateMessage variant="error" title="a" body="b" testID="failed" />
      </>,
    );
    expect(flatten(screen.getByTestId('blocked').props.style).backgroundColor).toBe(
      color.warning100,
    );
    expect(flatten(screen.getByTestId('failed').props.style).backgroundColor).toBe(
      color.error100,
    );
  });
});

describe('PartialFailureNotice', () => {
  it('says a retry does not charge again', async () => {
    // With money already taken, that is the question anybody has before
    // pressing the button.
    await render(
      <PartialFailureNotice
        total={40}
        succeeded={38}
        title="2 of 40 lines could not be set up"
        body="38 lines are ready."
        retryLabel="Retry the 2 that failed"
        noChargeNote="Retrying does not charge you again."
        onRetry={() => undefined}
        testID="partial"
      />,
    );
    expect(screen.getByTestId('partial-no-charge').props.children).toBe(
      'Retrying does not charge you again.',
    );
    expect(screen.getByTestId('partial-retry')).toBeTruthy();
  });

  it('offers no retry once nothing is left to retry', async () => {
    await render(
      <PartialFailureNotice
        total={40}
        succeeded={40}
        title="All lines are ready"
        body="40 lines are ready."
        retryLabel="Retry"
        noChargeNote="."
        onRetry={() => undefined}
        testID="partial"
      />,
    );
    expect(screen.queryByTestId('partial-retry')).toBeNull();
  });

  it('announces the whole outcome, not just the failure count', async () => {
    await render(
      <PartialFailureNotice
        total={40}
        succeeded={38}
        title="2 of 40 lines could not be set up"
        body="38 lines are ready."
        retryLabel="Retry"
        noChargeNote="Retrying does not charge you again."
        onRetry={() => undefined}
        testID="partial"
      />,
    );
    expect(screen.getByTestId('partial-summary').props.accessibilityLabel).toBe(
      '2 of 40 lines could not be set up. 38 lines are ready. Retrying does not charge you again.',
    );
    expect(screen.getByTestId('partial').props.accessible).not.toBe(true);
    expect(screen.getByTestId('partial-retry')).toBeTruthy();
  });
});

describe('announce', () => {
  it('does not double a full stop the copy already has', () => {
    // Found by the two tests above: `[a, b].join('. ')` on already-punctuated
    // translated copy produces "38 lines are ready.. Retrying…", and every
    // locale hits it at once.
    expect(announce('Ready.', 'Retry is free.')).toBe('Ready. Retry is free.');
  });

  it('adds one when the copy has none', () => {
    expect(announce('Ready', 'Retry is free')).toBe('Ready. Retry is free.');
  });

  it('respects other terminal punctuation', () => {
    expect(announce('Ready?', 'Now what…')).toBe('Ready? Now what…');
  });

  it('drops empty and whitespace-only parts', () => {
    expect(announce('Ready.', undefined, '   ', null, 'Done.')).toBe('Ready. Done.');
  });
});
