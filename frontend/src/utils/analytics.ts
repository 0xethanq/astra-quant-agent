/**
 * Lightweight first-party conversion event beacon.
 * Sent to `/t?...` (OpenResty returns 204 No Content immediately without cookies).
 */
export function trackEvent(
  eventName: string,
  props?: Record<string, string | number | boolean>,
): void {
  if (typeof window === 'undefined') return;
  try {
    const params = new URLSearchParams({
      ev: eventName,
      src: 'astraquant',
      path: window.location.pathname || '/',
    });
    if (props) {
      for (const [key, val] of Object.entries(props)) {
        if (val !== undefined && val !== null && val !== '') {
          params.set(key, String(val));
        }
      }
    }
    const url = `/t?${params.toString()}`;
    if (typeof navigator !== 'undefined' && typeof navigator.sendBeacon === 'function') {
      navigator.sendBeacon(url);
    } else if (typeof fetch === 'function') {
      void fetch(url, { method: 'GET', keepalive: true }).catch(() => undefined);
    }
  } catch {
    // Non-blocking analytics telemetry
  }
}
