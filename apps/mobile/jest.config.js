module.exports = {
  preset: '@react-native/jest-preset',
  setupFiles: [
    '@react-native-community/netinfo/jest/netinfo-mock.js',
  ],
  setupFilesAfterEnv: ['<rootDir>/jest.setup.js'],
  transformIgnorePatterns: [
    'node_modules/(?!(react-native|@react-native|react-native-contacts|react-native-callkeep|react-native-voip-push-notification)/)',
  ],
  collectCoverageFrom: ['src/**/*.{ts,tsx}', '!src/**/*.d.ts'],
};
