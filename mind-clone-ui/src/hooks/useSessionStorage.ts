export function readSession(key: string): string {
  try {
    return window.sessionStorage.getItem(key) || "";
  } catch {
    return "";
  }
}

export function writeSession(key: string, value: string): void {
  try {
    if (value) {
      window.sessionStorage.setItem(key, value);
    } else {
      window.sessionStorage.removeItem(key);
    }
  } catch {
    // session storage can be blocked by browser policy
  }
}
