/**
 * @format
 */
import { AppRegistry } from 'react-native';
import App from './App';
import { name as appName } from './app.json';

// Testing-infra-only seam (screenshotHarness/README.md): SCREENSHOT_HARNESS_MODE
// is inlined at build time by babel-plugin-transform-inline-environment-variables
// and must remain false for a real app build. Android release task-graph and
// iOS Release bundle-phase guards reject a production build if it is true.
const RootComponent =
  process.env.SCREENSHOT_HARNESS_MODE === 'true'
    ? require('./screenshotHarness/ScreenshotHarnessApp').ScreenshotHarnessApp
    : App;

AppRegistry.registerComponent(appName, () => RootComponent);
