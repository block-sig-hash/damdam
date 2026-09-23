import React from 'react';
import { cleanup, render } from '@testing-library/react-native';
import type { Receipt } from '../../api/accountClient';
import { i18n } from '../../i18n';
import { ReceiptsScreen } from './ReceiptsScreen';

const receipt: Receipt = {
  order_id: 'order-1',
  reference: 'ORD-1',
  placed_at: '2026-09-01T09:00:00Z',
  currency: 'NGN',
  total_amount: '5000.000000',
  payment_state: 'paid',
  lines: [{
    description: 'Forfait de connectivité exemple',
    quantity: 1,
    unit_amount: '5000.000000',
    total_amount: '5000.000000',
  }],
  organization_id: null,
};

afterEach(() => {
  cleanup();
  return i18n.changeLanguage('en');
});

it('shows a readable French receipt without changing the charged amount', async () => {
  await i18n.changeLanguage('fr');
  const view = await render(<ReceiptsScreen receipts={[receipt]} fromCache={false} onBack={() => undefined} />);

  expect(view.getByText('Forfait de connectivité exemple')).toBeTruthy();
  expect(view.getAllByText('NGN 5000.00')).toHaveLength(2);
  expect(view.getByText(/sept/i)).toBeTruthy();
  expect(view.getByText(/UTC/)).toBeTruthy();
  expect(view.queryByText(/2026-09-01T09:00:00Z/)).toBeNull();
  expect(view.queryByText(/5000\.000000/)).toBeNull();
});

it('retains nonzero sub-cent precision rather than silently rounding it', async () => {
  const precise = {
    ...receipt,
    total_amount: '5000.000001',
    lines: [{ ...receipt.lines[0], total_amount: '5000.000001' }],
  };
  const view = await render(<ReceiptsScreen receipts={[precise]} fromCache={false} onBack={() => undefined} />);

  expect(view.getAllByText('NGN 5000.000001')).toHaveLength(2);
});
