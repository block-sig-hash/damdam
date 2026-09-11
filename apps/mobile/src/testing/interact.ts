import { act, fireEvent, screen } from '@testing-library/react-native';

/**
 * Fire an interaction and let React settle before the next line runs.
 *
 * Without the `act` wrapper, a `fireEvent` in this setup schedules the state
 * update but does not flush it, so the very next statement reads the *previous*
 * render. That produces a specific and misleading failure: typing into a field
 * and then pressing submit sends the value the field had *before* the keystroke
 * — usually an empty string — and the test fails on a validation error that has
 * nothing to do with what it was checking.
 *
 * Asserting with `waitFor` hides the problem for assertions but not for
 * sequences, because the stale value has already been read by the time the
 * assertion retries.
 */

export async function type(testID: string, text: string): Promise<void> {
  await act(async () => {
    fireEvent.changeText(screen.getByTestId(testID), text);
  });
}

export async function press(testID: string): Promise<void> {
  await act(async () => {
    fireEvent.press(screen.getByTestId(testID));
  });
}
