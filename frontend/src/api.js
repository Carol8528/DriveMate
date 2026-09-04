async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.message || `请求失败（${response.status}）`);
  return data;
}

export const api = {
  health: () => request("/health"),
  meta: () => request("/api/v1/meta"),
  simulator: () => request("/api/v1/simulator/state"),
  run: (payload) => request("/api/v1/agent/runs", { method: "POST", body: JSON.stringify(payload) }),
  confirm: (runId, snapshot) => request(`/api/v1/agent/runs/${encodeURIComponent(runId)}/confirm`, { method: "POST", body: JSON.stringify({ snapshot }) }),
  cancel: (runId) => request(`/api/v1/agent/runs/${encodeURIComponent(runId)}/cancel`, { method: "POST", body: "{}" }),
  audit: (runId) => request(`/api/v1/audit/runs/${encodeURIComponent(runId)}`),
};
