// Manual mock for the scoped package, auto-applied by Jest to every
// test without needing jest.mock() calls per file — the package's
// own jest/async-storage-mock.js exports the mock object directly
// rather than registering itself, so it must be wired in this way
// (a setupFiles entry just runs it as a script, it doesn't register
// a module mock).
module.exports = require('@react-native-async-storage/async-storage/jest/async-storage-mock');
