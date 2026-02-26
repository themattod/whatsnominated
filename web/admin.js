const ALL_CATEGORIES = '__ALL__';
const ADMIN_PREFS_KEY = 'oscars:admin:prefs';
const EVENT_MODE_SIGNAL_KEY = 'oscars:event-mode-signal';
const ADMIN_LOGIN_PATH = '/admin-login.html';

const state = {
  year: null,
  years: [],
  categories: [],
  nominations: [],
  films: [],
  winnersByCategory: {},
  banner: {
    enabled: true,
    text: ''
  },
  eventMode: false,
  votingLocked: false,
  dashboard: {
    uniqueUsers: 0,
    usersCompared: 0,
    totalPicks: 0,
    winnerCategories: 0
  },
  csrfToken: '',
  ballotJumpCategory: '',
  poolTroubleshoot: {
    poolId: '',
    userEmail: '',
    results: [],
    selectedPoolId: '',
    detail: null
  }
};

const loadAdminPrefs = () => {
  try {
    const raw = localStorage.getItem(ADMIN_PREFS_KEY);
    if (!raw) {
      return {};
    }
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
};

const saveAdminPrefs = () => {
  localStorage.setItem(
    ADMIN_PREFS_KEY,
    JSON.stringify({
      year: state.year,
      ballotJumpCategory: state.ballotJumpCategory
    })
  );
};

const adminPrefs = loadAdminPrefs();
if (typeof adminPrefs.year === 'number') {
  state.year = adminPrefs.year;
}
if (typeof adminPrefs.ballotJumpCategory === 'string') {
  state.ballotJumpCategory = adminPrefs.ballotJumpCategory;
}

const yearSelect = document.getElementById('yearSelect');
const yearControlLabel = document.getElementById('yearControl');
const ballotJumpSelect = document.getElementById('ballotJumpSelect');
const stats = document.getElementById('stats');
const filmList = document.getElementById('filmList');
const adminFormTemplate = document.getElementById('adminFormTemplate');
const bannerForm = document.getElementById('bannerForm');
const bannerEnabledButton = document.getElementById('bannerEnabledButton');
const bannerText = document.getElementById('bannerText');
const bannerSaveStatus = document.getElementById('bannerSaveStatus');
const dashUniqueUsers = document.getElementById('dashUniqueUsers');
const dashUsersCompared = document.getElementById('dashUsersCompared');
const dashTotalPicks = document.getElementById('dashTotalPicks');
const dashWinnerCategories = document.getElementById('dashWinnerCategories');
const eventModeHeaderButton = document.getElementById('eventModeHeaderButton');
const votingLockHeaderButton = document.getElementById('votingLockHeaderButton');
const clearWinnersButton = document.getElementById('clearWinnersButton');
const eventModeSaveStatus = document.getElementById('eventModeSaveStatus');
const adminLogoutButton = document.getElementById('adminLogoutButton');
const poolTroubleshootForm = document.getElementById('poolTroubleshootForm');
const poolTroubleshootPoolId = document.getElementById('poolTroubleshootPoolId');
const poolTroubleshootUserEmail = document.getElementById('poolTroubleshootUserEmail');
const poolTroubleshootReset = document.getElementById('poolTroubleshootReset');
const poolTroubleshootStatus = document.getElementById('poolTroubleshootStatus');
const poolTroubleshootResults = document.getElementById('poolTroubleshootResults');
let bannerSaveStatusTimer = null;
let eventModeSaveStatusTimer = null;

const api = async (path, options = {}) => {
  const run = async () => {
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
    return response;
  };

  let response = await run();
  if (response.status === 403) {
    let details = '';
    try {
      details = await response.text();
    } catch {
      details = '';
    }
    if (details.includes('Invalid CSRF token')) {
      const session = await getAdminSession();
      if (!session.loggedIn) {
        window.location.href = ADMIN_LOGIN_PATH;
        throw new Error('Admin login required.');
      }
      state.csrfToken = session.csrfToken || '';
      response = await run();
    } else {
      throw new Error(`API error ${response.status}: ${path}${details ? ` - ${details}` : ''}`);
    }
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

const unique = (items) => [...new Set(items)];
const slugify = (value) =>
  String(value || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');

const sizeSelectToOptions = (selectEl) => {
  const longest = Math.max(...[...selectEl.options].map((o) => o.textContent.length), 1);
  selectEl.style.width = `${Math.max(longest + 4, 8)}ch`;
};

const loadYears = async () => {
  const payload = await api('/api/years');
  state.years = payload.years;
  const hasYear = state.years.some((y) => y.year === state.year);
  if (!hasYear && state.years.length) {
    state.year = state.years[0].year;
  }
};

const loadNominees = async () => {
  const payload = await api(
    `/api/nominees?year=${state.year}&category=${encodeURIComponent(ALL_CATEGORIES)}`
  );
  state.categories = payload.categories;
  state.films = payload.films;
  state.nominations = payload.nominations;
  state.winnersByCategory = payload.winnersByCategory || {};
  state.banner = payload.banner || { enabled: true, text: '' };
  state.eventMode = Boolean(payload.eventMode);
  state.votingLocked = Boolean(payload.votingLocked);
};

const loadDashboard = async () => {
  const payload = await api(`/api/admin/dashboard?year=${state.year}`);
  state.dashboard = {
    uniqueUsers: payload.uniqueUsers || 0,
    usersCompared: payload.usersCompared || 0,
    totalPicks: payload.totalPicks || 0,
    winnerCategories: payload.winnerCategories || 0
  };
};

const loadDashboardSafe = async () => {
  try {
    await loadDashboard();
  } catch {
    state.dashboard = {
      uniqueUsers: 0,
      usersCompared: 0,
      totalPicks: 0,
      winnerCategories: 0
    };
  }
};

const loadPoolTroubleshootSearch = async () => {
  const query = new URLSearchParams();
  if (state.poolTroubleshoot.poolId) {
    query.set('poolId', state.poolTroubleshoot.poolId);
  }
  if (state.poolTroubleshoot.userEmail) {
    query.set('userEmail', state.poolTroubleshoot.userEmail);
  }
  query.set('year', String(state.year));
  query.set('limit', '50');
  const payload = await api(`/api/admin/pools/troubleshoot?${query.toString()}`);
  state.poolTroubleshoot.results = Array.isArray(payload.pools) ? payload.pools : [];
  if (
    state.poolTroubleshoot.selectedPoolId &&
    !state.poolTroubleshoot.results.some((row) => row.poolId === state.poolTroubleshoot.selectedPoolId)
  ) {
    state.poolTroubleshoot.selectedPoolId = '';
    state.poolTroubleshoot.detail = null;
  }
};

const loadPoolTroubleshootDetail = async (poolId) => {
  const payload = await api(`/api/admin/pools/${encodeURIComponent(poolId)}/troubleshoot`);
  state.poolTroubleshoot.selectedPoolId = poolId;
  state.poolTroubleshoot.detail = payload;
};

const updatePoolPaymentStatus = async (poolId, userId, status, rejectionReason = '') => {
  await api(`/api/admin/pools/${encodeURIComponent(poolId)}/payments`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ userId, status, rejectionReason })
  });
};

const recomputePoolScores = async (poolId) => {
  await api(`/api/admin/pools/${encodeURIComponent(poolId)}/recompute-scores`, { method: 'POST' });
};

const buildYearOptions = () => {
  if (yearControlLabel) {
    yearControlLabel.style.display = state.years.length <= 1 ? 'none' : '';
  }
  yearSelect.innerHTML = '';
  for (const y of state.years) {
    const option = document.createElement('option');
    option.value = y.year;
    option.textContent = String(y.year);
    yearSelect.append(option);
  }
  yearSelect.value = String(state.year);
  sizeSelectToOptions(yearSelect);
};

const alphabeticalCategoryNames = () =>
  state.categories
    .map((category) => category.name)
    .sort((a, b) => a.localeCompare(b));

const nominationMaps = () => {
  const nomineeByFilmAndCategory = new Map();
  const categoryFilmIds = new Map();

  for (const nomination of state.nominations) {
    nomineeByFilmAndCategory.set(`${nomination.filmId}::${nomination.category}`, nomination.nominee || '');
    const filmIds = categoryFilmIds.get(nomination.category) || [];
    filmIds.push(nomination.filmId);
    categoryFilmIds.set(nomination.category, filmIds);
  }

  return { nomineeByFilmAndCategory, categoryFilmIds };
};

const buildBallotJumpOptions = () => {
  ballotJumpSelect.innerHTML = '';

  const empty = document.createElement('option');
  empty.value = '';
  empty.textContent = 'Select category';
  ballotJumpSelect.append(empty);

  for (const categoryName of alphabeticalCategoryNames()) {
    const option = document.createElement('option');
    option.value = categoryName;
    option.textContent = categoryName;
    ballotJumpSelect.append(option);
  }

  if (!alphabeticalCategoryNames().includes(state.ballotJumpCategory)) {
    state.ballotJumpCategory = '';
  }
  ballotJumpSelect.value = state.ballotJumpCategory;
  sizeSelectToOptions(ballotJumpSelect);
};

const fmtDateTime = (value) => (value ? String(value).replace('T', ' ') : '');
const fmtCents = (value, currency = 'USD') => {
  const amount = Number(value || 0);
  return `${(amount / 100).toFixed(2)} ${String(currency || 'USD').toUpperCase()}`;
};

const renderPoolTroubleshoot = () => {
  if (!poolTroubleshootResults) {
    return;
  }
  poolTroubleshootResults.innerHTML = '';
  const rows = state.poolTroubleshoot.results || [];
  if (rows.length === 0) {
    const empty = document.createElement('p');
    empty.className = 'pools-empty';
    empty.textContent = 'No pools found for the current filter.';
    poolTroubleshootResults.append(empty);
    return;
  }

  const list = document.createElement('div');
  list.className = 'pool-troubleshoot-results';

  for (const row of rows) {
    const card = document.createElement('article');
    card.className = 'pool-troubleshoot-card';
    card.dataset.poolId = row.poolId;

    const top = document.createElement('div');
    top.className = 'pool-troubleshoot-top';
    const title = document.createElement('h4');
    title.textContent = `${row.name || 'Untitled Pool'} (${row.poolId})`;
    const meta = document.createElement('p');
    meta.className = 'small-note';
    meta.textContent = `Year ${row.year} • Owner ${row.ownerEmail || 'unknown'} • Members ${row.memberCount || 0} • Submissions ${row.submissionCount || 0} • Payment Exceptions ${row.paymentExceptionCount || 0}`;
    top.append(title, meta);

    const actions = document.createElement('div');
    actions.className = 'pool-troubleshoot-actions';
    const inspectBtn = document.createElement('button');
    inspectBtn.type = 'button';
    inspectBtn.dataset.action = 'pool-troubleshoot-inspect';
    inspectBtn.dataset.poolId = row.poolId;
    inspectBtn.textContent =
      state.poolTroubleshoot.selectedPoolId === row.poolId ? 'Refresh Detail' : 'Inspect';
    const recomputeBtn = document.createElement('button');
    recomputeBtn.type = 'button';
    recomputeBtn.dataset.action = 'pool-troubleshoot-recompute';
    recomputeBtn.dataset.poolId = row.poolId;
    recomputeBtn.textContent = 'Recompute Scores';
    actions.append(inspectBtn, recomputeBtn);

    card.append(top, actions);

    if (
      state.poolTroubleshoot.selectedPoolId === row.poolId &&
      state.poolTroubleshoot.detail &&
      state.poolTroubleshoot.detail.pool
    ) {
      const detail = state.poolTroubleshoot.detail;
      const detailWrap = document.createElement('div');
      detailWrap.className = 'pool-troubleshoot-detail';

      const summary = document.createElement('p');
      summary.className = 'small-note';
      summary.textContent = `Mode ${detail.pool.scoringMode || 'standard'} • Entry ${detail.pool.entryMode || 'free'} • Payment required ${detail.pool.paymentRequiredToScore ? 'Yes' : 'No'} • Updated ${fmtDateTime(detail.pool.updatedAt)}`;
      detailWrap.append(summary);

      const issues = document.createElement('div');
      issues.className = 'pool-troubleshoot-issues';
      const missing = (detail.issues?.missingSubmissions || []).length;
      const exceptions = (detail.issues?.paymentExceptions || []).length;
      issues.textContent = `Issues: ${missing} missing submission(s), ${exceptions} payment exception(s).`;
      detailWrap.append(issues);

      const paymentsTitle = document.createElement('h5');
      paymentsTitle.textContent = 'Payments';
      detailWrap.append(paymentsTitle);

      const payments = detail.payments || [];
      if (payments.length === 0) {
        const none = document.createElement('p');
        none.className = 'small-note';
        none.textContent = 'No payment records.';
        detailWrap.append(none);
      } else {
        const tableWrap = document.createElement('div');
        tableWrap.className = 'audit-table-wrap';
        const table = document.createElement('table');
        table.className = 'audit-table';
        const thead = document.createElement('thead');
        thead.innerHTML =
          '<tr><th>Member</th><th>Amount</th><th>Status</th><th>Reported</th><th>Update</th></tr>';
        const tbody = document.createElement('tbody');
        for (const payment of payments) {
          const tr = document.createElement('tr');
          const memberTd = document.createElement('td');
          memberTd.textContent = `${payment.displayName || payment.userId} (${payment.email || 'no email'})`;
          const amountTd = document.createElement('td');
          amountTd.textContent = fmtCents(payment.amountCents, payment.currency);
          const statusTd = document.createElement('td');
          statusTd.textContent = payment.status || '';
          const reportedTd = document.createElement('td');
          reportedTd.textContent = fmtDateTime(payment.reportedAt || payment.createdAt);
          const actionTd = document.createElement('td');
          const statusSelect = document.createElement('select');
          statusSelect.dataset.action = 'pool-payment-status';
          statusSelect.dataset.poolId = row.poolId;
          statusSelect.dataset.userId = payment.userId;
          for (const optionValue of ['pending', 'self_reported', 'confirmed', 'rejected', 'waived']) {
            const option = document.createElement('option');
            option.value = optionValue;
            option.textContent = optionValue;
            statusSelect.append(option);
          }
          statusSelect.value = payment.status || 'pending';
          const applyBtn = document.createElement('button');
          applyBtn.type = 'button';
          applyBtn.dataset.action = 'pool-payment-apply';
          applyBtn.dataset.poolId = row.poolId;
          applyBtn.dataset.userId = payment.userId;
          applyBtn.textContent = 'Apply';
          actionTd.append(statusSelect, applyBtn);
          tr.append(memberTd, amountTd, statusTd, reportedTd, actionTd);
          tbody.append(tr);
        }
        table.append(thead, tbody);
        tableWrap.append(table);
        detailWrap.append(tableWrap);
      }

      const scoresTitle = document.createElement('h5');
      scoresTitle.textContent = 'Scores';
      detailWrap.append(scoresTitle);
      const scoreRows = detail.scores || [];
      if (scoreRows.length === 0) {
        const none = document.createElement('p');
        none.className = 'small-note';
        none.textContent = 'No score rows.';
        detailWrap.append(none);
      } else {
        const scoreList = document.createElement('div');
        scoreList.className = 'pool-score-list';
        for (const score of scoreRows) {
          const line = document.createElement('p');
          line.textContent = `#${score.rankPosition || '-'} ${score.displayName || score.userId} • ${score.totalPoints || 0} pts • ${score.correctCount || 0} correct`;
          scoreList.append(line);
        }
        detailWrap.append(scoreList);
      }
      card.append(detailWrap);
    }
    list.append(card);
  }
  poolTroubleshootResults.append(list);
};

const jumpToCategory = (categoryName) => {
  if (!categoryName) {
    return;
  }
  const id = `admin-ballot-category-${slugify(categoryName)}`;
  const node = document.getElementById(id);
  if (!node) {
    return;
  }
  node.scrollIntoView({ behavior: 'smooth', block: 'start' });
};

const renderStats = () => {
  const categoryCount = state.categories.length;
  const nominationCount = state.nominations.length;
  stats.textContent = `Managing ${nominationCount} nomination${nominationCount === 1 ? '' : 's'} across ${categoryCount} categories.`;
};

const renderFilms = () => {
  renderStats();
  const isBannerEnabled = Boolean(state.banner?.enabled);
  bannerEnabledButton.setAttribute('aria-pressed', isBannerEnabled ? 'true' : 'false');
  bannerEnabledButton.textContent = isBannerEnabled ? 'Banner Enabled' : 'Enable Banner';
  bannerText.value = state.banner?.text || '';
  dashUniqueUsers.textContent = String(state.dashboard?.uniqueUsers || 0);
  dashUsersCompared.textContent = String(state.dashboard?.usersCompared || 0);
  dashTotalPicks.textContent = String(state.dashboard?.totalPicks || 0);
  dashWinnerCategories.textContent = String(state.dashboard?.winnerCategories || 0);
  eventModeHeaderButton.setAttribute('aria-pressed', state.eventMode ? 'true' : 'false');
  eventModeHeaderButton.textContent = state.eventMode ? "We're Doing it Live!" : 'Enable Live Mode';
  votingLockHeaderButton.setAttribute('aria-pressed', state.votingLocked ? 'true' : 'false');
  votingLockHeaderButton.textContent = state.votingLocked ? '🔒Voting Locked' : 'Lock Voting';
  clearWinnersButton.disabled = state.votingLocked;
  clearWinnersButton.textContent = 'Clear Winners';
  filmList.innerHTML = '';
  const maps = nominationMaps();
  const filmsById = new Map(state.films.map((film) => [film.id, film]));

  for (const categoryName of alphabeticalCategoryNames()) {
    const section = document.createElement('section');
    section.className = 'ballot-category-section';
    section.id = `admin-ballot-category-${slugify(categoryName)}`;

    const headerMain = document.createElement('div');
    headerMain.className = 'ballot-category-header-main';

    const categoryMeta = document.createElement('div');
    categoryMeta.className = 'ballot-category-meta';

    const heading = document.createElement('h3');
    heading.className = 'ballot-category-title';
    heading.textContent = categoryName;

    const winnerFilmId = state.winnersByCategory?.[categoryName];
    const hasWinner = Boolean(winnerFilmId);
    const status = document.createElement('span');
    status.className = `ballot-category-status ${hasWinner ? 'picked' : 'missing'}`;
    status.textContent = hasWinner ? 'Winner Set' : 'Winner Missing';

    const winnerColumnLabel = document.createElement('span');
    winnerColumnLabel.className = 'ballot-column-label ballot-vote-column-label';
    winnerColumnLabel.textContent = 'Winner';

    categoryMeta.append(heading, status);
    headerMain.append(categoryMeta, winnerColumnLabel);
    section.append(headerMain);

    const filmIds = unique(maps.categoryFilmIds.get(categoryName) || []);
    const films = filmIds
      .map((filmId) => filmsById.get(filmId))
      .filter(Boolean)
      .sort((a, b) => a.title.localeCompare(b.title));

    if (films.length === 0) {
      const empty = document.createElement('p');
      empty.className = 'ballot-empty';
      empty.textContent = 'No films in this category.';
      section.append(empty);
      filmList.append(section);
      continue;
    }

    for (const film of films) {
      const card = document.createElement('article');
      card.className = 'film-card ballot-card admin-ballot-card';

      const main = document.createElement('div');
      main.className = 'ballot-main';

      const copy = document.createElement('div');
      copy.className = 'ballot-copy';

      const title = document.createElement('h2');
      title.className = 'film-title';
      title.textContent = film.title;

      const nominee = maps.nomineeByFilmAndCategory.get(`${film.id}::${categoryName}`) || '';
      const meta = document.createElement('p');
      meta.className = 'film-meta';
      meta.textContent = nominee || 'Nominee details unavailable.';
      copy.append(title, meta);

      const actions = document.createElement('div');
      actions.className = 'ballot-actions';
      const winnerCheckbox = document.createElement('input');
      winnerCheckbox.type = 'checkbox';
      winnerCheckbox.className = 'ballot-vote-checkbox';
      winnerCheckbox.dataset.action = 'winner-checkbox';
      winnerCheckbox.dataset.category = categoryName;
      winnerCheckbox.dataset.filmId = film.id;
      winnerCheckbox.checked = winnerFilmId === film.id;
      winnerCheckbox.setAttribute('aria-label', `Set ${film.title} as winner for ${categoryName}`);
      actions.append(winnerCheckbox);

      main.append(copy, actions);
      card.append(main);

      const adminForm = adminFormTemplate.content.firstElementChild.cloneNode(true);
      adminForm.dataset.filmId = film.id;
      adminForm.elements.freeToWatch.checked = Boolean(film.freeToWatch);
      adminForm.elements.whereToWatchUrl.value = film.whereToWatchOverrideUrl || '';
      adminForm.elements.posterUrl.value = film.posterOverrideUrl || '';
      card.append(adminForm);

      section.append(card);
    }

    filmList.append(section);
  }
};

const render = () => {
  buildYearOptions();
  buildBallotJumpOptions();
  renderFilms();
  renderPoolTroubleshoot();
};

const refresh = async () => {
  await loadNominees();
  await loadDashboardSafe();
  await loadPoolTroubleshootSearch();
  saveAdminPrefs();
  render();
};

const updateWhereToWatch = async (filmId, url, freeToWatch) => {
  await api('/api/admin/where-to-watch', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ year: state.year, filmId, url, freeToWatch })
  });
};

const updatePoster = async (filmId, url) => {
  await api('/api/admin/poster', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ year: state.year, filmId, url })
  });
};

const updateBanner = async (enabled, text) => {
  await api('/api/admin/banner', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ year: state.year, enabled, text })
  });
};

const updateEventMode = async (enabled) => {
  await api('/api/admin/event-mode', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ year: state.year, enabled })
  });
};

const updateVotingLock = async (enabled) => {
  await api('/api/admin/voting-lock', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ year: state.year, enabled })
  });
};

const updateWinner = async (category, filmId, winner) => {
  await api('/api/admin/winner', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ year: state.year, category, filmId, winner })
  });
};

const getAdminFormFields = (form) => {
  const whereToWatchUrlEl = form.elements.namedItem('whereToWatchUrl');
  const freeToWatchEl = form.elements.namedItem('freeToWatch');
  const posterUrlEl = form.elements.namedItem('posterUrl');

  if (
    !(whereToWatchUrlEl instanceof HTMLInputElement) ||
    !(freeToWatchEl instanceof HTMLInputElement) ||
    !(posterUrlEl instanceof HTMLInputElement)
  ) {
    throw new Error('Form fields are missing. Refresh and try again.');
  }

  return { whereToWatchUrlEl, freeToWatchEl, posterUrlEl };
};

const wireEvents = () => {
  adminLogoutButton.addEventListener('click', async () => {
    await api('/api/admin-auth/logout', { method: 'POST' });
    window.location.href = ADMIN_LOGIN_PATH;
  });

  yearSelect.addEventListener('change', async (event) => {
    state.year = Number(event.target.value);
    state.ballotJumpCategory = '';
    saveAdminPrefs();
    await refresh();
  });

  ballotJumpSelect.addEventListener('change', () => {
    state.ballotJumpCategory = ballotJumpSelect.value;
    saveAdminPrefs();
    jumpToCategory(state.ballotJumpCategory);
  });

  bannerForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (bannerSaveStatusTimer) {
      clearTimeout(bannerSaveStatusTimer);
      bannerSaveStatusTimer = null;
    }
    try {
      await updateBanner(Boolean(state.banner?.enabled), bannerText.value.trim());
      await loadNominees();
      await loadDashboardSafe();
      renderFilms();
      bannerSaveStatus.textContent = 'Saved.';
      bannerSaveStatus.classList.remove('error');
      bannerSaveStatusTimer = setTimeout(() => {
        bannerSaveStatus.textContent = '';
      }, 2200);
    } catch (error) {
      bannerSaveStatus.textContent = `Unable to save banner. ${error.message}`;
      bannerSaveStatus.classList.add('error');
    }
  });

  bannerEnabledButton.addEventListener('click', () => {
    state.banner = {
      ...(state.banner || {}),
      enabled: !Boolean(state.banner?.enabled)
    };
    renderFilms();
  });

  eventModeHeaderButton.addEventListener('click', async () => {
    if (eventModeSaveStatusTimer) {
      clearTimeout(eventModeSaveStatusTimer);
      eventModeSaveStatusTimer = null;
    }
    const nextEnabled = !state.eventMode;
    try {
      await updateEventMode(nextEnabled);
      await loadNominees();
      renderFilms();
      localStorage.setItem(
        EVENT_MODE_SIGNAL_KEY,
        JSON.stringify({ year: state.year, enabled: nextEnabled, ts: Date.now() })
      );
      eventModeSaveStatus.textContent = 'Saved.';
      eventModeSaveStatus.classList.remove('error');
      eventModeSaveStatusTimer = setTimeout(() => {
        eventModeSaveStatus.textContent = '';
      }, 2200);
    } catch (error) {
      eventModeSaveStatus.textContent = `Unable to save event mode. ${error.message}`;
      eventModeSaveStatus.classList.add('error');
    }
  });

  votingLockHeaderButton.addEventListener('click', async () => {
    if (eventModeSaveStatusTimer) {
      clearTimeout(eventModeSaveStatusTimer);
      eventModeSaveStatusTimer = null;
    }
    const nextEnabled = !state.votingLocked;
    try {
      await updateVotingLock(nextEnabled);
      await loadNominees();
      renderFilms();
      eventModeSaveStatus.textContent = 'Saved.';
      eventModeSaveStatus.classList.remove('error');
      eventModeSaveStatusTimer = setTimeout(() => {
        eventModeSaveStatus.textContent = '';
      }, 2200);
    } catch (error) {
      eventModeSaveStatus.textContent = `Unable to save voting lock. ${error.message}`;
      eventModeSaveStatus.classList.add('error');
    }
  });

  clearWinnersButton.addEventListener('click', async () => {
    if (state.votingLocked) {
      return;
    }
    const entries = Object.entries(state.winnersByCategory || {});
    if (entries.length === 0) {
      eventModeSaveStatus.textContent = 'No winners to clear.';
      eventModeSaveStatus.classList.remove('error');
      return;
    }
    if (eventModeSaveStatusTimer) {
      clearTimeout(eventModeSaveStatusTimer);
      eventModeSaveStatusTimer = null;
    }
    try {
      for (const [category, filmId] of entries) {
        await updateWinner(category, filmId, false);
      }
      await loadNominees();
      await loadDashboardSafe();
      renderFilms();
      eventModeSaveStatus.textContent = 'Winners cleared.';
      eventModeSaveStatus.classList.remove('error');
      eventModeSaveStatusTimer = setTimeout(() => {
        eventModeSaveStatus.textContent = '';
      }, 2200);
    } catch (error) {
      eventModeSaveStatus.textContent = `Unable to clear winners. ${error.message}`;
      eventModeSaveStatus.classList.add('error');
    }
  });

  poolTroubleshootForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    poolTroubleshootStatus.textContent = '';
    poolTroubleshootStatus.classList.remove('error');
    state.poolTroubleshoot.poolId = (poolTroubleshootPoolId.value || '').trim();
    state.poolTroubleshoot.userEmail = (poolTroubleshootUserEmail.value || '').trim();
    try {
      await loadPoolTroubleshootSearch();
      state.poolTroubleshoot.selectedPoolId = '';
      state.poolTroubleshoot.detail = null;
      renderPoolTroubleshoot();
      poolTroubleshootStatus.textContent = `Found ${state.poolTroubleshoot.results.length} pool(s).`;
    } catch (error) {
      poolTroubleshootStatus.textContent = `Unable to search pools. ${error.message}`;
      poolTroubleshootStatus.classList.add('error');
    }
  });

  poolTroubleshootReset.addEventListener('click', async () => {
    poolTroubleshootPoolId.value = '';
    poolTroubleshootUserEmail.value = '';
    state.poolTroubleshoot.poolId = '';
    state.poolTroubleshoot.userEmail = '';
    state.poolTroubleshoot.selectedPoolId = '';
    state.poolTroubleshoot.detail = null;
    try {
      await loadPoolTroubleshootSearch();
      renderPoolTroubleshoot();
      poolTroubleshootStatus.textContent = '';
      poolTroubleshootStatus.classList.remove('error');
    } catch (error) {
      poolTroubleshootStatus.textContent = `Unable to reset search. ${error.message}`;
      poolTroubleshootStatus.classList.add('error');
    }
  });

  poolTroubleshootResults.addEventListener('click', async (event) => {
    const inspectButton = event.target.closest('[data-action="pool-troubleshoot-inspect"]');
    if (inspectButton) {
      const poolId = inspectButton.dataset.poolId;
      try {
        poolTroubleshootStatus.textContent = 'Loading detail...';
        await loadPoolTroubleshootDetail(poolId);
        renderPoolTroubleshoot();
        poolTroubleshootStatus.textContent = 'Detail loaded.';
        poolTroubleshootStatus.classList.remove('error');
      } catch (error) {
        poolTroubleshootStatus.textContent = `Unable to load detail. ${error.message}`;
        poolTroubleshootStatus.classList.add('error');
      }
      return;
    }

    const recomputeButton = event.target.closest('[data-action="pool-troubleshoot-recompute"]');
    if (recomputeButton) {
      const poolId = recomputeButton.dataset.poolId;
      try {
        poolTroubleshootStatus.textContent = 'Recomputing scores...';
        await recomputePoolScores(poolId);
        await loadPoolTroubleshootSearch();
        if (state.poolTroubleshoot.selectedPoolId === poolId) {
          await loadPoolTroubleshootDetail(poolId);
        }
        renderPoolTroubleshoot();
        poolTroubleshootStatus.textContent = 'Scores recomputed.';
        poolTroubleshootStatus.classList.remove('error');
      } catch (error) {
        poolTroubleshootStatus.textContent = `Unable to recompute scores. ${error.message}`;
        poolTroubleshootStatus.classList.add('error');
      }
      return;
    }

    const paymentApplyButton = event.target.closest('[data-action="pool-payment-apply"]');
    if (paymentApplyButton) {
      const poolId = paymentApplyButton.dataset.poolId;
      const userId = paymentApplyButton.dataset.userId;
      const selector = `select[data-action="pool-payment-status"][data-pool-id="${poolId}"][data-user-id="${userId}"]`;
      const paymentSelect = poolTroubleshootResults.querySelector(selector);
      if (!(paymentSelect instanceof HTMLSelectElement)) {
        return;
      }
      const status = paymentSelect.value;
      let rejectionReason = '';
      if (status === 'rejected') {
        rejectionReason = window.prompt('Optional rejection reason', '') || '';
      }
      try {
        poolTroubleshootStatus.textContent = 'Updating payment...';
        await updatePoolPaymentStatus(poolId, userId, status, rejectionReason.trim());
        await loadPoolTroubleshootSearch();
        if (state.poolTroubleshoot.selectedPoolId === poolId) {
          await loadPoolTroubleshootDetail(poolId);
        }
        renderPoolTroubleshoot();
        poolTroubleshootStatus.textContent = 'Payment updated.';
        poolTroubleshootStatus.classList.remove('error');
      } catch (error) {
        poolTroubleshootStatus.textContent = `Unable to update payment. ${error.message}`;
        poolTroubleshootStatus.classList.add('error');
      }
    }
  });

  filmList.addEventListener('submit', async (event) => {
    const form = event.target.closest('.admin-form');
    if (!form) {
      return;
    }

    event.preventDefault();
    try {
      const filmId = form.dataset.filmId;
      const { whereToWatchUrlEl, freeToWatchEl, posterUrlEl } = getAdminFormFields(form);
      await updateWhereToWatch(
        filmId,
        whereToWatchUrlEl.value.trim(),
        freeToWatchEl.checked
      );
      await updatePoster(filmId, posterUrlEl.value.trim());
      await loadNominees();
      await loadDashboardSafe();
      renderFilms();
    } catch (error) {
      alert(`Unable to save overrides. ${error.message}`);
    }
  });

  filmList.addEventListener('change', async (event) => {
    const winnerCheckbox = event.target.closest('[data-action="winner-checkbox"]');
    if (!winnerCheckbox) {
      return;
    }
    const category = winnerCheckbox.dataset.category;
    const filmId = winnerCheckbox.dataset.filmId;
    const currentlyWinner = state.winnersByCategory?.[category] === filmId;
    const nextWinner = Boolean(winnerCheckbox.checked);
    if (currentlyWinner === nextWinner) {
      return;
    }
    try {
      await updateWinner(category, filmId, nextWinner);
      await loadNominees();
      await loadDashboardSafe();
      renderFilms();
    } catch (error) {
      winnerCheckbox.checked = currentlyWinner;
      alert(`Unable to save winner. ${error.message}`);
    }
  });

  filmList.addEventListener('click', async (event) => {

    const clearButton = event.target.closest('.clear-override-button');
    if (clearButton) {
      try {
        const form = clearButton.closest('.admin-form');
        const { freeToWatchEl } = getAdminFormFields(form);
        await updateWhereToWatch(
          form.dataset.filmId,
          '',
          freeToWatchEl.checked
        );
        await loadNominees();
        await loadDashboardSafe();
        renderFilms();
      } catch (error) {
        alert(`Unable to clear watch override. ${error.message}`);
      }
      return;
    }

    const clearPosterButton = event.target.closest('.clear-poster-button');
    if (clearPosterButton) {
      try {
        const form = clearPosterButton.closest('.admin-form');
        await updatePoster(form.dataset.filmId, '');
        await loadNominees();
        await loadDashboardSafe();
        renderFilms();
      } catch (error) {
        alert(`Unable to clear poster override. ${error.message}`);
      }
      return;
    }
  });
};

const start = async () => {
  const session = await getAdminSession();
  if (!session.loggedIn) {
    window.location.href = ADMIN_LOGIN_PATH;
    return;
  }
  state.csrfToken = session.csrfToken || '';
  await loadYears();
  await refresh();
  wireEvents();
};

start().catch((error) => {
  filmList.innerHTML = `<p>Failed to load admin data: ${error.message}</p>`;
});
