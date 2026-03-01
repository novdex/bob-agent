/**
 * useStreaming — SSE streaming hook for real-time chat responses.
 *
 * Connects to POST /api/stream and yields tokens as they arrive.
 */
import { useState, useCallback, useRef } from "react";

export type StreamState = {
  text: string;
  done: boolean;
  error: string | null;
  tokensStreamed: number;
};

const INITIAL: StreamState = { text: "", done: true, error: null, tokensStreamed: 0 };

export function useStreaming() {
  const [state, setState] = useState<StreamState>(INITIAL);
  const abortRef = useRef<AbortController | null>(null);

  const stream = useCallback(
    async (payload: {
      message: string;
      owner_id: number;
      model?: string;
      temperature?: number;
      max_tokens?: number;
    }): Promise<string> => {
      // Reset
      setState({ text: "", done: false, error: null, tokensStreamed: 0 });

      // Abort any in-flight stream
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      let accumulated = "";
      let tokens = 0;

      try {
        const res = await fetch("/api/stream", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
          signal: controller.signal,
        });

        if (!res.ok) {
          const errText = await res.text().catch(() => `HTTP ${res.status}`);
          throw new Error(errText);
        }

        const reader = res.body?.getReader();
        if (!reader) throw new Error("No response body");

        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done: readerDone, value } = await reader.read();
          if (readerDone) break;

          buffer += decoder.decode(value, { stream: true });

          // Process complete SSE lines
          const lines = buffer.split("\n");
          // Keep the last (possibly incomplete) line in buffer
          buffer = lines.pop() ?? "";

          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed || !trimmed.startsWith("data:")) continue;

            const dataStr = trimmed.slice(trimmed.startsWith("data: ") ? 6 : 5);
            if (dataStr === "[DONE]") {
              setState((prev) => ({ ...prev, done: true }));
              return accumulated;
            }

            try {
              const parsed = JSON.parse(dataStr);

              if (parsed.error) {
                setState((prev) => ({ ...prev, done: true, error: parsed.error }));
                return accumulated;
              }

              if (parsed.done) {
                // Final event with full_response
                if (parsed.full_response) {
                  accumulated = parsed.full_response;
                }
                tokens = parsed.tokens_streamed ?? tokens;
                setState({ text: accumulated, done: true, error: null, tokensStreamed: tokens });
                return accumulated;
              }

              // Incremental token
              const token = parsed.token ?? "";
              if (token) {
                accumulated += token;
                tokens++;
                setState({ text: accumulated, done: false, error: null, tokensStreamed: tokens });
              }
            } catch {
              // Not JSON — treat as raw text token
              accumulated += dataStr;
              tokens++;
              setState({ text: accumulated, done: false, error: null, tokensStreamed: tokens });
            }
          }
        }

        setState((prev) => ({ ...prev, done: true }));
        return accumulated;
      } catch (err: unknown) {
        if (err instanceof DOMException && err.name === "AbortError") {
          setState((prev) => ({ ...prev, done: true }));
          return accumulated;
        }
        const msg = err instanceof Error ? err.message : String(err);
        setState((prev) => ({ ...prev, done: true, error: msg }));
        throw err;
      }
    },
    [],
  );

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    setState((prev) => ({ ...prev, done: true }));
  }, []);

  return { ...state, stream, cancel };
}
