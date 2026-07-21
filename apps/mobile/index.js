/**
 * @format
 */
import { AppRegistry } from 'react-native';
import App from './App';
import { name as appName } from './app.json';
import { handleAndroidIncomingCallPayload } from './src/services/callKit';

// Testing-infra-only seam (screenshotHarness/README.md): SCREENSHOT_HARNESS_MODE
// is inlined at build time by babel-plugin-transform-inline-environment-variables
// and is never set for a real app build, so this branch is dead code in
// production -- only CI's screenshot-generation job ever sets it.
const RootComponent =
  process.env.SCREENSHOT_HARNESS_MODE === 'true'
    ? require('./screenshotHarness/ScreenshotHarnessApp').ScreenshotHarnessApp
    : App;

AppRegistry.registerComponent(appName, () => RootComponent);

// Android only -- the task name here must match CallHeadlessTaskService.kt's
// TASK_KEY exactly. Wakes the JS engine to report an incoming call to the
// native call UI even if the app was fully killed; see callKit.ts's
// handleAndroidIncomingCallPayload doc comment for the full flow.
AppRegistry.registerHeadlessTask(
  'DamDamIncomingCall',
  () => handleAndroidIncomingCallPayload,
);
