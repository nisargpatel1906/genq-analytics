export const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

/**
 * Optional API key read from VITE_GENQ_API_KEY env var.
 * When set, it is sent as the X-API-Key header on every request.
 * Leave blank in local dev (backend auth is disabled when GENQ_API_KEY is empty).
 */
export const API_KEY: string | undefined = import.meta.env.VITE_GENQ_API_KEY || undefined;

/**
 * Returns standard headers for all API requests.
 * Includes X-API-Key when VITE_GENQ_API_KEY is configured.
 */
export function apiHeaders(extra?: Record<string, string>): Record<string, string> {
  const headers: Record<string, string> = {
    ...extra,
  };
  if (API_KEY) {
    headers['X-API-Key'] = API_KEY;
  }
  return headers;
}
