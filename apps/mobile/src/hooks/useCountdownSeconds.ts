import { useEffect, useState } from 'react';

/** Ticks down to 0 once per second; restarts whenever `totalSeconds` changes. */
export function useCountdownSeconds(totalSeconds: number): number {
  const [remaining, setRemaining] = useState(totalSeconds);

  useEffect(() => {
    setRemaining(totalSeconds);
    if (totalSeconds <= 0) {
      return undefined;
    }
    const id = setInterval(() => {
      setRemaining((current) => (current <= 1 ? 0 : current - 1));
    }, 1000);
    return () => clearInterval(id);
  }, [totalSeconds]);

  return remaining;
}
