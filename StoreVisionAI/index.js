/**
 * @format
 */

import { AppRegistry, LogBox } from 'react-native';
import App from './App';
import { name as appName } from './app.json';

// Demo mode: keep development warnings and debugger prompts from covering the
// StoreVision camera/audit HUD on an emulator or presentation device.
LogBox.ignoreAllLogs(true);

AppRegistry.registerComponent(appName, () => App);
