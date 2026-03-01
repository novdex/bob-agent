import { useEffect, useRef, useState } from "react";

type SSEOptions = {
  onEvent: (data: Record<string, unknown>) => void;
  onError?: (err: Event) => void;
  token?: string;
};

export function useSSE(url: string | null, options: SSEOptions) {
  const [connected, setConnected] = useState(false);
  const retryRef = useRef(1000);
  const optionsRef = useRef(options);
  optionsRef.current = options;

  useEffect(() => {
    if (!url) {
      setConnected(false);
      return;
    }

    let es: EventSource | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let stopped = false;

    const stableUrl = url; // captured after null check above

    function connect() {
      if (stopped) return;
      const fullUrl = optionsRef.current.token
        ? `${stableUrl}${stableUrl.includes("?") ? "&" : "?"}token=${encodeURIComponent(optionsRef.current.token)}`
        : stableUrl;

      es = new EventSource(fullUrl);

      es.onopen = () => {
        setConnected(true);
        retryRef.current = 1000;
      };

      es.onmessage = (evt) => {
        try {
          const data = JSON.parse(evt.data);
          optionsRef.current.onEvent(data);
        } catch { /* skip non-JSON */ }
      };

      es.onerror = (evt) => {
        setConnected(false);
        es?.close();
        optionsRef.current.onError?.(evt);
        if (!stopped) {
          timer = setTimeout(connect, retryRef.current);
          retryRef.current = Math.min(retryRef.current * 2, 30_000);
        }
      };
    }

    connect();

    return () => {
      stopped = true;
      es?.close();
      if (timer) clearTimeout(timer);
      setConnected(false);
    };
  }, [url]);

  return { connected };
}
