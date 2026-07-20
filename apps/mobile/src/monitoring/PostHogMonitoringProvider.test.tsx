import React from 'react';
import {Text} from 'react-native';
import {render} from '@testing-library/react-native';
import {POSTHOG_API_KEY} from '../config/env';
import {
  POSTHOG_OPTIONS,
  PostHogMonitoringProvider,
} from './PostHogMonitoringProvider';

const testWithConfiguredKey = POSTHOG_API_KEY ? it : it.skip;

describe('PostHog mobile monitoring', () => {
  it('enables official SDK exception autocapture for JS and native crashes', () => {
    expect(POSTHOG_OPTIONS.errorTracking).toEqual({
      autocapture: {
        uncaughtExceptions: true,
        unhandledRejections: true,
        nativeCrashes: true,
      },
    });
  });

  testWithConfiguredKey('initializes the real provider when a build key exists', async () => {
    const {getByText} = await render(
      <PostHogMonitoringProvider>
        <Text>monitored application</Text>
      </PostHogMonitoringProvider>,
    );

    expect(getByText('monitored application')).toBeTruthy();
  });
});
