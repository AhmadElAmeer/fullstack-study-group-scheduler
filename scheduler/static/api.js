// Small fetch wrapper: JSON in, JSON out, and the server's error message on failure.
export async function api(method, path, body, key) {
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (key) headers["X-Member-Key"] = key;
  const res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  if (res.status === 204) return null;
  let data = null;
  try {
    data = await res.json();
  } catch {
    // not JSON (e.g. a proxy error page)
  }
  if (!res.ok) {
    const err = new Error((data && data.error) || `Request failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return data;
}

// localStorage can be missing or throw (private windows, blocked storage); the app still works,
// you just have to rejoin to edit again.
export const store = {
  get(k) {
    try { return JSON.parse(localStorage.getItem(k)); } catch { return null; }
  },
  set(k, v) {
    try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* ignore */ }
  },
  remove(k) {
    try { localStorage.removeItem(k); } catch { /* ignore */ }
  },
};
