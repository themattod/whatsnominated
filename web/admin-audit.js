const ADMIN_LOGIN_PATH = '/admin-login.html';

const state = {
  csrfToken: '',
  action: '',
  success: 'all',
  limit: 100,
  logs: [],
  actions: []
};

const auditActionSelect = document.getElementById('auditActionSelect');
const auditSuccessSelect = document.getElementById('auditSuccessSelect');
const auditLimitSelect = document.getElementById('auditLimitSelect');
const auditRefreshButton = document.getElementById('auditRefreshButton');
const auditStatus = document.getElementById('auditStatus');
const auditTableBody = document.getElementById('auditTableBody');
const adminLogoutButton = document.getElementById('adminLogoutButton');

const api = async (path, options = {}) => {
  const method = (options.method || 'GET').toUpperCase();
  const headers = new Headers(options.headers || {});
  if (state.csrfToken && (method === 'POST' || method === 'PUT' || method === 'DELETE')) {
    headers.set('X-CSRF-Token', state.csrfToken);
  }
  const response = await fetch(path, { ...options, headers });
  if (response.status === 401) {
    window.location.href = ADMIN_LOGIN_PATH;
    throw new Error('Admin login required.');
  }
  if (!response.ok) {
    let details = '';
    try {
      details = await response.text();
    } catch {
      details = '';
    }
    throw new Error(`API error ${response.status}: ${path}${details ? ` - ${details}` : ''}`);
  }
  return response.json();
};

const getAdminSession = async () => {
  const response = await fetch('/api/admin-auth/session');
  if (!response.ok) {
    throw new Error(`API error ${response.status}: /api/admin-auth/session`);
  }
  return response.json();
};

const sizeSelectToOptions = (selectEl) => {
  const longest = Math.max(...[...selectEl.options].map((o) => o.textContent.length), 1);
  selectEl.style.width = `${Math.max(longest + 4, 8)}ch`;
};

const loadAuditLogs = async () => {
  const params = new URLSearchParams();
  if (state.action) {
    params.set('action', state.action);
  }
  params.set('success', state.success || 'all');
  params.set('limit', String(state.limit || 100));
  const paths = [
    `/api/admin/audit-logs?${params.toString()}`,
    `/api/admin/audit-logs/?${params.toString()}`,
    `/api/admin/audit_logs?${params.toString()}`
  ];
  let lastError = null;
  for (const path of paths) {
    try {
      const payload = await api(path);
      state.logs = payload.logs || [];
      state.actions = payload.actions || [];
      return;
    } catch (error) {
      if (!String(error.message || '').includes('API error 404')) {
        throw error;
      }
      lastError = error;
    }
  }
  throw lastError || new Error('Unable to load audit logs.');
};

const render = () => {
  auditActionSelect.innerHTML = '<option value="">All actions</option>';
  for (const item of state.actions) {
    const option = document.createElement('option');
    option.value = item.action;
    option.textContent = `${item.action} (${item.count})`;
    auditActionSelect.append(option);
  }

  auditActionSelect.value = state.action;
  auditSuccessSelect.value = state.success;
  auditLimitSelect.value = String(state.limit);
  sizeSelectToOptions(auditActionSelect);
  sizeSelectToOptions(auditSuccessSelect);
  sizeSelectToOptions(auditLimitSelect);

  auditTableBody.innerHTML = '';
  for (const row of state.logs) {
    const tr = document.createElement('tr');
    const time = document.createElement('td');
    const action = document.createElement('td');
    const status = document.createElement('td');
    const actor = document.createElement('td');
    const ip = document.createElement('td');
    const details = document.createElement('td');

    time.textContent = row.createdAt || '';
    action.textContent = row.action || '';
    status.textContent = row.success ? 'Success' : 'Failure';
    status.className = row.success ? 'audit-success' : 'audit-failure';
    actor.textContent = row.actorEmail || '-';
    ip.textContent = row.requestIp || '-';
    details.textContent = JSON.stringify(row.details || {});

    tr.append(time, action, status, actor, ip, details);
    auditTableBody.append(tr);
  }

  auditStatus.textContent = `${state.logs.length} log entries loaded.`;
};

const wireEvents = () => {
  adminLogoutButton.addEventListener('click', async () => {
    await api('/api/admin-auth/logout', { method: 'POST' });
    window.location.href = ADMIN_LOGIN_PATH;
  });

  auditActionSelect.addEventListener('change', async () => {
    state.action = auditActionSelect.value;
    await loadAuditLogs();
    render();
  });

  auditSuccessSelect.addEventListener('change', async () => {
    state.success = auditSuccessSelect.value;
    await loadAuditLogs();
    render();
  });

  auditLimitSelect.addEventListener('change', async () => {
    state.limit = Number(auditLimitSelect.value);
    await loadAuditLogs();
    render();
  });

  auditRefreshButton.addEventListener('click', async () => {
    await loadAuditLogs();
    render();
  });
};

const start = async () => {
  const session = await getAdminSession();
  if (!session.loggedIn) {
    window.location.href = ADMIN_LOGIN_PATH;
    return;
  }
  state.csrfToken = session.csrfToken || '';
  await loadAuditLogs();
  render();
  wireEvents();
};

start().catch((error) => {
  auditStatus.textContent = `Failed to load audit logs: ${error.message}`;
  auditStatus.classList.add('error');
});
