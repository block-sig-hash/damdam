const reactNativeConfig = require('@react-native/eslint-config/flat');

module.exports = [
  {
    ignores: ['node_modules/**', 'coverage/**'],
  },
  ...reactNativeConfig,
];
