import Geolocation from '@react-native-community/geolocation';
import {optionalCheckInLocation} from './checkInLocation';

const requestAuthorization = Geolocation.requestAuthorization as jest.Mock;
const getCurrentPosition = Geolocation.getCurrentPosition as jest.Mock;

beforeEach(() => {
  jest.useFakeTimers();
  jest.clearAllMocks();
});

afterEach(() => jest.useRealTimers());

it('AC-15.2: returns permitted GPS within the connected-send budget', async () => {
  requestAuthorization.mockImplementationOnce(success => success());
  getCurrentPosition.mockImplementationOnce(success =>
    success({coords: {latitude: 21.422487, longitude: 39.826206}}),
  );

  await expect(optionalCheckInLocation()).resolves.toEqual({
    latitude: 21.422487,
    longitude: 39.826206,
  });
});

it('AC-15.3: a stalled first-use permission prompt releases sync after two seconds', async () => {
  requestAuthorization.mockImplementationOnce(() => undefined);
  let settled = false;
  const location = optionalCheckInLocation().then(result => {
    settled = true;
    return result;
  });

  await jest.advanceTimersByTimeAsync(1999);
  expect(settled).toBe(false);
  await jest.advanceTimersByTimeAsync(1);

  await expect(location).resolves.toBeUndefined();
});
