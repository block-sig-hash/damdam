import { NativeModules, Platform } from 'react-native';
import { markEsimActivated } from '../api/esimClient';
import {
  activateAndConfirmAndroidProfile,
  confirmActivatedAfterConnectivity,
  getActivationPath,
  runSingleFlight,
} from './esimActivation';

jest.mock('../api/esimClient', () => ({ markEsimActivated: jest.fn() }));
const originalOs = Platform.OS;

afterEach(() => {
  Object.defineProperty(Platform, 'OS', { configurable: true, value: originalOs });
  delete NativeModules.EsimActivationModule;
  jest.clearAllMocks();
});

it('AC-13.4: single-flight guard suppresses a concurrent double tap', async () => {
  const state = { current: false };
  let resolve!: (value: string) => void;
  const action = jest.fn(() => new Promise<string>(done => { resolve = done; }));
  const first = runSingleFlight(state, action);
  const second = runSingleFlight(state, action);
  expect(action).toHaveBeenCalledTimes(1);
  await expect(second).resolves.toBeUndefined();
  resolve('done');
  await expect(first).resolves.toBe('done');
  expect(state.current).toBe(false);
});

it('AC-13.5: iOS always uses the manual path without querying Android capability', async () => {
  Object.defineProperty(Platform, 'OS', { configurable: true, value: 'ios' });
  NativeModules.EsimActivationModule = { getActivationCapability: jest.fn() };
  await expect(getActivationPath('iccid')).resolves.toBe('manual');
  expect(NativeModules.EsimActivationModule.getActivationCapability).not.toHaveBeenCalled();
});

it('AC-13.4/13.5: branches only on the native carrier-privilege capability result', async () => {
  Object.defineProperty(Platform, 'OS', { configurable: true, value: 'android' });
  NativeModules.EsimActivationModule = {
    getActivationCapability: jest.fn()
      .mockResolvedValueOnce({ canSwitch: true, reason: 'supported' })
      .mockResolvedValueOnce({ canSwitch: false, reason: 'carrier_privileges_missing' }),
  };
  await expect(getActivationPath('iccid')).resolves.toBe('single_tap');
  await expect(getActivationPath('iccid')).resolves.toBe('manual');
});

it('AC-13.6: marks activated only after validated connectivity succeeds', async () => {
  const check = jest.fn().mockResolvedValueOnce(false).mockResolvedValueOnce(true);
  const wait = jest.fn().mockResolvedValue(undefined);
  (markEsimActivated as jest.Mock).mockResolvedValue({ status: 'activated' });
  await expect(confirmActivatedAfterConnectivity('token', 'package-1', {
    attempts: 2,
    intervalMs: 1,
    checkConnectivity: check,
    wait,
  })).resolves.toBe('activated');
  expect(wait).toHaveBeenCalledTimes(1);
  expect(markEsimActivated).toHaveBeenCalledWith('token', 'package-1');
});

it('AC-13.6: does not mark activated when connectivity never validates', async () => {
  await expect(confirmActivatedAfterConnectivity('token', 'package-1', {
    attempts: 2,
    checkConnectivity: jest.fn().mockResolvedValue(false),
    wait: jest.fn().mockResolvedValue(undefined),
  })).resolves.toBe('not_connected');
  expect(markEsimActivated).not.toHaveBeenCalled();
});

it('AC-13.4: invokes the native switch once before checking connectivity', async () => {
  Object.defineProperty(Platform, 'OS', { configurable: true, value: 'android' });
  const activateProfile = jest.fn().mockResolvedValue(undefined);
  NativeModules.EsimActivationModule = { activateProfile };
  (markEsimActivated as jest.Mock).mockResolvedValue({ status: 'activated' });
  await activateAndConfirmAndroidProfile('token', 'package-1', 'iccid', {
    attempts: 1,
    checkConnectivity: jest.fn().mockResolvedValue(true),
  });
  expect(activateProfile).toHaveBeenCalledTimes(1);
  expect(markEsimActivated).toHaveBeenCalledTimes(1);
});
