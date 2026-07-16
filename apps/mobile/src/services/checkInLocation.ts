import Geolocation from '@react-native-community/geolocation';
import {PermissionsAndroid, Platform} from 'react-native';
import type {CheckInLocation} from './checkInOutbox';

async function permissionGranted(): Promise<boolean> {
  if (Platform.OS === 'android') {
    return (
      (await PermissionsAndroid.request(
        PermissionsAndroid.PERMISSIONS.ACCESS_FINE_LOCATION,
      )) === PermissionsAndroid.RESULTS.GRANTED
    );
  }
  return new Promise(resolve => {
    Geolocation.requestAuthorization(
      () => resolve(true),
      () => resolve(false),
    );
  });
}

export async function optionalCheckInLocation(): Promise<CheckInLocation | undefined> {
  if (!(await permissionGranted())) return undefined;
  return new Promise(resolve => {
    Geolocation.getCurrentPosition(
      position =>
        resolve({
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
        }),
      () => resolve(undefined),
      {enableHighAccuracy: true, timeout: 2000, maximumAge: 30_000},
    );
  });
}
