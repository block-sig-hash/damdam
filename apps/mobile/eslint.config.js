const reactNativeConfig = require('@react-native/eslint-config/flat');

module.exports = [
  {
    ignores: ['node_modules/**', 'coverage/**'],
  },
  ...reactNativeConfig,
  {
    // scripts/ holds CI tooling that runs under plain Node on the runner,
    // not inside the React Native app bundle -- so it needs Node globals
    // the React Native config does not declare, and the screenshot
    // validator reads PNG headers, which is bitwise by nature.
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
    rules: {
      'no-bitwise': 'off',
    },
  },
];
