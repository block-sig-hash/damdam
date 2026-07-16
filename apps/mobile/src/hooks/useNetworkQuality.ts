import NetInfo, { type NetInfoCellularGeneration, type NetInfoState } from '@react-native-community/netinfo';
import { useEffect, useState } from 'react';

export type NetworkQuality = 'poor' | 'fair' | 'good' | 'excellent';

export function qualityFromNetwork(state: NetInfoState): NetworkQuality {
  if (!state.isConnected || state.isInternetReachable === false) return 'poor';
  if (state.type === 'wifi' || state.type === 'ethernet') return 'excellent';
  if (state.type === 'cellular') {
    const generation = state.details.cellularGeneration as NetInfoCellularGeneration | null;
    if (generation === '5g') return 'excellent';
    if (generation === '4g') return 'good';
    if (generation === '3g') return 'fair';
  }
  return 'poor';
}

export function useNetworkQuality(): { connected: boolean; quality: NetworkQuality } {
  const [result, setResult] = useState<{ connected: boolean; quality: NetworkQuality }>({
    connected: true,
    quality: 'good',
  });
  useEffect(
    () =>
      NetInfo.addEventListener((state) =>
        setResult({
          connected: Boolean(state.isConnected && state.isInternetReachable !== false),
          quality: qualityFromNetwork(state),
        }),
      ),
    [],
  );
  return result;
}
