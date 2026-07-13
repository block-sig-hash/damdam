import { useEffect, useState } from 'react';

/** Whole seconds elapsed since `since` (a Date.now() timestamp), ticking every second. */
export function useElapsedSeconds(since: number): number {
  const [elapsed, setElapsed] = useState(() => Math.floor((Date.now() - since) / 1000));

  useEffect(() => {
    setElapsed(Math.floor((Date.now() - since) / 1000));
    const id = setInterval(() => {
      setElapsed(Math.floor((Date.now() - since) / 1000));
    }, 1000);
    return () => clearInterval(id);
  }, [since]);

  return elapsed;
}
