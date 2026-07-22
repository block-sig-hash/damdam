module.exports = {
  presets: ['module:@react-native/babel-preset'],
  plugins: [
    [
      'transform-inline-environment-variables',
      {
        include: [
          'API_BASE_URL',
          'POSTHOG_API_KEY',
          'POSTHOG_HOST',
          'SUPPORT_WHATSAPP_NUMBER',
          'SCREENSHOT_HARNESS_MODE',
        ],
      },
    ],
  ],
};
