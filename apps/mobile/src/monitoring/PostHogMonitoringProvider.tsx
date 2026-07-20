import React from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import {
  PostHogProvider,
  type PostHogOptions,
} from 'posthog-react-native';
import {POSTHOG_API_KEY, POSTHOG_HOST} from '../config/env';

export const POSTHOG_OPTIONS: PostHogOptions = {
  host: POSTHOG_HOST,
  customStorage: AsyncStorage,
  errorTracking: {
    autocapture: {
      uncaughtExceptions: true,
      unhandledRejections: true,
      nativeCrashes: true,
    },
  },
};

export function PostHogMonitoringProvider({
  children,
}: React.PropsWithChildren): React.JSX.Element {
  if (!POSTHOG_API_KEY) {
    return <>{children}</>;
  }

  return (
    <PostHogProvider
      apiKey={POSTHOG_API_KEY}
      options={POSTHOG_OPTIONS}
      autocapture={false}>
      {children}
    </PostHogProvider>
  );
}
