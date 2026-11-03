const API_BASE = "http://localhost:8000";

export async function fetchJson(endpoint, options = {}) {
  const url = endpoint.startsWith("http") ? endpoint : `${API_BASE}${endpoint}`;
  const res = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });
  if (!res.ok) {
    let errDetail = res.statusText;
    try {
      const body = await res.json();
      errDetail = body.detail || body.message || errDetail;
    } catch {}
    throw new Error(errDetail);
  }
  return res.json();
}
