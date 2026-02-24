import { useEffect } from "react";
import type { PanelKey } from "../types";
import { PANELS } from "../constants";

/**
 * Keyboard navigation: Ctrl+1..9 switches panels, Escape refocuses.
 */
export function useKeyboardNav(setActivePanel: (key: PanelKey) => void) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Ctrl+1 through Ctrl+9 — switch to panel by index
      if (e.ctrlKey && !e.shiftKey && !e.altKey && !e.metaKey) {
        const num = parseInt(e.key, 10);
        if (num >= 1 && num <= 9 && num <= PANELS.length) {
          e.preventDefault();
          setActivePanel(PANELS[num - 1].key);
        }
      }
    };

    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [setActivePanel]);
}
