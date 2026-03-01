import { useEffect, useRef } from "react";

/**
 * Calls `callback` immediately and then every `intervalMs` milliseconds.
 * Uses a ref for the callback to avoid stale closures.
 */
export function usePolling(
  callback: () => void | Promise<void>,
  intervalMs: number,
  deps: readonly unknown[] = []
): void {
  const callbackRef = useRef(callback);
  callbackRef.current = callback;

  useEffect(() => {
    void callbackRef.current();
    const timer = window.setInterval(() => void callbackRef.current(), intervalMs);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs, ...deps]);
}
