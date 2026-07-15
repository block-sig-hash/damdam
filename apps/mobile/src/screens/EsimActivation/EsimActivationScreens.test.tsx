import React from 'react';
import { cleanup, fireEvent, render } from '@testing-library/react-native';
import { EsimActivationGuideScreen } from './EsimActivationGuideScreen';
import { EsimActivationPromptScreen } from './EsimActivationPromptScreen';

afterEach(async () => {
  await cleanup();
});

it('AC-13.5: makes the guide the primary action on iOS/manual-capability devices', async () => {
  const onGuide = jest.fn();
  const view = await render(
    <EsimActivationPromptScreen
      activationPath="manual"
      onActivate={jest.fn()}
      onManualGuide={onGuide}
    />,
  );
  fireEvent.press(view.getByTestId('arrival-activate'));
  expect(onGuide).toHaveBeenCalledTimes(1);
  expect(view.getByText("You've arrived in Saudi Arabia. Tap to activate your DamDam data — takes 30 seconds.")).toBeTruthy();
});

it('AC-13.4: exposes single-tap activation only for the supported capability path', async () => {
  const onActivate = jest.fn();
  const view = await render(
    <EsimActivationPromptScreen
      activationPath="single_tap"
      onActivate={onActivate}
      onManualGuide={jest.fn()}
    />,
  );
  fireEvent.press(view.getByTestId('arrival-activate'));
  expect(onActivate).toHaveBeenCalledTimes(1);
  expect(view.getByText('Use manual guide')).toBeTruthy();
});

it('AC-13.5: renders matched guide shell and explicit placeholder status', async () => {
  const view = await render(
    <EsimActivationGuideScreen
      platform="android"
      deviceModel="Tecno Camon 20"
      onShowQrCode={jest.fn()}
      onConfirmActivated={jest.fn()}
    />,
  );
  expect(view.getByText(/Tecno Camon \/ Spark/)).toBeTruthy();
  expect(view.getByTestId('android-guide-content-gap')).toBeTruthy();
  expect(view.getAllByText(/Settings|SIM|DamDam|mobile data/).length).toBeGreaterThan(0);
});
