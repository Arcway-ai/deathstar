// api.js — Fetch wrapper with auth token

const Api = (() => {
  const TOKEN_KEY = 'deathstar_api_token';

  function getToken() {
    return localStorage.getItem(TOKEN_KEY) || '';
  }

  function setToken(token) {
    localStorage.setItem(TOKEN_KEY, token);
  }

  async function request(path, options = {}) {
    const token = getToken();
    const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const resp = await fetch(path, { ...options, headers });

    if (resp.status === 401) {
      throw new Error('Authentication failed. Check your API token in Settings.');
    }

    if (!resp.ok) {
      let detail = `HTTP ${resp.status}`;
      try {
        const body = await resp.json();
        detail = body.message || body.detail || detail;
      } catch { /* ignore parse error */ }
      throw new Error(detail);
    }

    return resp.json();
  }

  function get(path) {
    return request(path, { method: 'GET' });
  }

  function post(path, body) {
    return request(path, { method: 'POST', body: JSON.stringify(body) });
  }

  function del(path) {
    return request(path, { method: 'DELETE' });
  }

  return { getToken, setToken, get, post, del };
})();
