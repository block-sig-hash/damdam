/**
 * @format
 */
import { AppRegistry } from 'react-native';
import App from './App';
import { name as appName } from './app.json';
import { handleAndroidIncomingCallPayload } from './src/services/callKit';

AppRegistry.registerComponent(appName, () => App);

// Android only -- the task name here must match CallHeadlessTaskService.kt's
// TASK_KEY exactly. Wakes the JS engine to report an incoming call to the
// native call UI even if the app was fully killed; see callKit.ts's
// handleAndroidIncomingCallPayload doc comment for the full flow.
AppRegistry.registerHeadlessTask(
  'DamDamIncomingCall',
  () => handleAndroidIncomingCallPayload,
);
