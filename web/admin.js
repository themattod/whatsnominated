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
  category: ALL_CATEGORIES,
  sort: 'title'
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
      category: state.category,
      sort: state.sort
    })
  );
};

const adminPrefs = loadAdminPrefs();
if (typeof adminPrefs.year === 'number') {
  state.year = adminPrefs.year;
}
if (typeof adminPrefs.category === 'string') {
  state.category = adminPrefs.category;
}
if (adminPrefs.sort === 'title' || adminPrefs.sort === 'nominations') {
  state.sort = adminPrefs.sort;
}

const yearSelect = document.getElementById('yearSelect');
const yearControlLabel = document.getElementById('yearControl');
const categorySelect = document.getElementById('categorySelect');
const sortSelect = document.getElementById('sortSelect');
const sortWrap = document.getElementById('sortWrap');
const stats = document.getElementById('stats');
const filmList = document.getElementById('filmList');
const cardTemplate = document.getElementById('filmCardTemplate');
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
const eventModeSaveStatus = document.getElementById('eventModeSaveStatus');
const adminLogoutButton = document.getElementById('adminLogoutButton');
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
const resolveWatchUrl = (film) => {
  const url = (film.whereToWatchUrl || '').trim();
  if (!url) {
    return '';
  }
  const lower = url.toLowerCase();
  if (lower.includes('justwatch.com') && (lower.includes('/search') || lower.includes('?q='))) {
    return '';
  }
  return url;
};
const posterProxyUrl = (filmId) =>
  `/api/poster-image?year=${encodeURIComponent(String(state.year))}&filmId=${encodeURIComponent(filmId)}`;
const resolvePosterUrl = (film) => posterProxyUrl(film.id);

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
    `/api/nominees?year=${state.year}&category=${encodeURIComponent(state.category)}`
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

const buildCategoryOptions = () => {
  categorySelect.innerHTML = '';
  const all = document.createElement('option');
  all.value = ALL_CATEGORIES;
  all.textContent = 'All films';
  categorySelect.append(all);

  for (const category of state.categories) {
    const option = document.createElement('option');
    option.value = category.name;
    option.textContent = category.name;
    categorySelect.append(option);
  }

  const hasCategory =
    state.category === ALL_CATEGORIES || state.categories.some((c) => c.name === state.category);
  if (!hasCategory) {
    state.category = ALL_CATEGORIES;
  }
  categorySelect.value = state.category;
  sizeSelectToOptions(categorySelect);
};

const renderStats = () => {
  stats.textContent = `Managing ${state.films.length} film${state.films.length === 1 ? '' : 's'} in this view.`;
};

const sortedFilms = () => {
  const nominationCounts = new Map();
  for (const nomination of state.nominations) {
    nominationCounts.set(nomination.filmId, (nominationCounts.get(nomination.filmId) || 0) + 1);
  }

  const films = [...state.films];
  if (state.sort === 'nominations') {
    films.sort((a, b) => {
      const countA = nominationCounts.get(a.id) || 0;
      const countB = nominationCounts.get(b.id) || 0;
      if (countB !== countA) {
        return countB - countA;
      }
      return a.title.localeCompare(b.title);
    });
  } else {
    films.sort((a, b) => a.title.localeCompare(b.title));
  }

  return films;
};

const renderFilms = () => {
  sortWrap.hidden = false;
  sortSelect.value = state.sort;
  sizeSelectToOptions(sortSelect);

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
  filmList.innerHTML = '';

  for (const film of sortedFilms()) {
    const card = cardTemplate.content.firstElementChild.cloneNode(true);
    const nominatedIn = state.nominations.filter((n) => n.filmId === film.id);
    const categoryNames = unique(nominatedIn.map((n) => n.category));

    const posterImage = card.querySelector('.poster-image');
    const posterFallback = card.querySelector('.poster-fallback');
    posterImage.src = resolvePosterUrl(film);
    posterImage.alt = `${film.title} poster`;
    posterImage.hidden = false;
    posterFallback.hidden = true;
    posterImage.onload = () => {
      posterImage.hidden = false;
      posterFallback.hidden = true;
    };
    posterImage.onerror = () => {
      posterImage.hidden = true;
      posterFallback.hidden = false;
    };

    const winnerButton = card.querySelector('.winner-button');
    if (state.category !== ALL_CATEGORIES) {
      const category = state.category;
      const winnerFilmId = state.winnersByCategory?.[category];
      const isWinner = winnerFilmId === film.id;
      winnerButton.hidden = false;
      winnerButton.disabled = false;
      winnerButton.dataset.filmId = film.id;
      winnerButton.dataset.category = category;
      winnerButton.setAttribute('aria-pressed', isWinner ? 'true' : 'false');
      winnerButton.textContent = isWinner ? 'Winner 🏆' : 'Winner';
    } else {
      winnerButton.hidden = false;
      winnerButton.disabled = true;
      winnerButton.dataset.filmId = '';
      winnerButton.dataset.category = '';
      winnerButton.setAttribute('aria-pressed', 'false');
      winnerButton.textContent = 'Winner (choose category)';
    }

    card.querySelector('.film-title').textContent = film.title;

    const meta = card.querySelector('.film-meta');
    if (state.category === ALL_CATEGORIES) {
      meta.textContent = `Nominated in ${categoryNames.length} categor${categoryNames.length === 1 ? 'y' : 'ies'}.`;
    } else {
      const nominees = nominatedIn
        .filter((n) => n.category === state.category)
        .map((n) => n.nominee)
        .filter(Boolean);
      meta.textContent = nominees.length
        ? `Nominee(s): ${nominees.join(' • ')}`
        : 'Nominee details unavailable.';
    }

    const tags = card.querySelector('.tags');
    for (const name of categoryNames) {
      const link = document.createElement('button');
      link.type = 'button';
      link.className = 'tag category-link';
      link.dataset.category = name;
      link.textContent = name;
      tags.append(link);
    }

    const availabilityList = card.querySelector('.availability');
    const wrapper = document.createElement('div');
    const dt = document.createElement('dt');
    const dd = document.createElement('dd');
    const watchUrl = resolveWatchUrl(film);
    if (watchUrl) {
      const labelLink = document.createElement('a');
      labelLink.href = watchUrl;
      labelLink.target = '_blank';
      labelLink.rel = 'noopener noreferrer';
      labelLink.textContent = film.freeToWatch ? 'Free to Watch' : 'Where to Watch';
      dt.append(labelLink);
    } else {
      dt.textContent = 'Unavailable';
    }
    dd.textContent = '';
    wrapper.append(dt, dd);
    availabilityList.append(wrapper);

    const adminForm = card.querySelector('.admin-form');
    adminForm.dataset.filmId = film.id;
    adminForm.elements.freeToWatch.checked = Boolean(film.freeToWatch);
    adminForm.elements.whereToWatchUrl.value = film.whereToWatchOverrideUrl || '';
    adminForm.elements.posterUrl.value = film.posterOverrideUrl || '';

    filmList.append(card);
  }
};

const render = () => {
  buildYearOptions();
  buildCategoryOptions();
  renderFilms();
};

const refresh = async () => {
  await loadNominees();
  await loadDashboardSafe();
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
    state.category = ALL_CATEGORIES;
    saveAdminPrefs();
    await refresh();
  });

  categorySelect.addEventListener('change', async (event) => {
    state.category = event.target.value;
    saveAdminPrefs();
    await refresh();
  });

  sortSelect.addEventListener('change', () => {
    state.sort = sortSelect.value;
    saveAdminPrefs();
    renderFilms();
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

  filmList.addEventListener('click', async (event) => {
    const winnerButton = event.target.closest('.winner-button');
    if (winnerButton) {
      const category = winnerButton.dataset.category;
      const filmId = winnerButton.dataset.filmId;
      const current = state.winnersByCategory?.[category] === filmId;
      await updateWinner(category, filmId, !current);
      await loadDashboardSafe();
      if (current) {
        delete state.winnersByCategory[category];
      } else {
        state.winnersByCategory[category] = filmId;
      }
      renderFilms();
      return;
    }

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

    const link = event.target.closest('.category-link');
    if (!link) {
      return;
    }

    const nextCategory = link.dataset.category;
    state.category = nextCategory;
    categorySelect.value = nextCategory;
    saveAdminPrefs();
    await refresh();
    window.scrollTo({ top: 0, behavior: 'smooth' });
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
