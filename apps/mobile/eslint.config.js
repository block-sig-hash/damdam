const reactNativeConfig = require('@react-native/eslint-config/flat');

module.exports = [
  {
    ignores: ['node_modules/**', 'coverage/**'],
  },
  ...reactNativeConfig,
  {
    // scripts/ holds CI tooling that runs under plain Node on the runner,
    // not inside the React Native app bundle -- so it needs Node globals
    // the React Native config does not declare.
    files: ['scripts/**/*.js'],
    languageOptions: {
      globals: {
        Buffer: 'readonly',
        __dirname: 'readonly',
        console: 'readonly',
        module: 'writable',
        process: 'readonly',
        require: 'readonly',
      },
    },
  },
  {
    files: ['scripts/validateScreenshots.test.js'],
    // Only the synthetic PNG fixture builder needs bitwise CRC32 operations.
    rules: {'no-bitwise': 'off'},
  },
];
