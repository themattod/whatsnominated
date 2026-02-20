const ALL_CATEGORIES = '__ALL__';
const DEFAULT_CATEGORY = 'Actor in a Leading Role';
const CATEGORY_VIEW_ORDER = [
  'Actor in a Leading Role',
  'Actor in a Supporting Role',
  'Actress in a Leading Role',
  'Actress in a Supporting Role',
  'Animated Feature Film',
  'Animated Short Film',
  'Casting',
  'Cinematography',
  'Costume Design',
  'Directing',
  'Documentary Feature Film',
  'Documentary Short Film',
  'Film Editing',
  'International Feature Film',
  'Live Action Short Film',
  'Makeup and Hairstyling',
  'Music (Original Score)',
  'Music (Original Song)',
  'Best Picture',
  'Production Design',
  'Sound',
  'Visual Effects',
  'Writing (Adapted Screenplay)',
  'Writing (Original Screenplay)'
];
const LIVE_SYNC_INTERVAL_MS = 5000;
const USER_PREFS_KEY = 'oscars:user:prefs';
const EVENT_MODE_SIGNAL_KEY = 'oscars:event-mode-signal';
const makeUserKey = () =>
  (typeof crypto !== 'undefined' && crypto.randomUUID)
    ? crypto.randomUUID()
    : `user-${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;

const state = {
  year: null,
  years: [],
  categories: [],
  nominations: [],
  films: [],
  winnersByCategory: {},
  votingLocked: false,
  eventMode: false,
  picksByCategory: {},
  seenFilmIds: new Set(),
  performance: {
    winnerCategoryCount: 0,
    userCorrectCount: 0,
    betterThanPercent: 0,
    comparedUserCount: 0,
    rankPosition: 1,
    rankedUserCount: 0,
    tiedUserCount: 1
  },
  category: DEFAULT_CATEGORY,
  sort: 'title',
  banner: {
    enabled: true,
    text: ''
  },
  userKey: localStorage.getItem('oscars:user-key') || makeUserKey()
};

localStorage.setItem('oscars:user-key', state.userKey);

const loadUserPrefs = () => {
  try {
    const raw = localStorage.getItem(USER_PREFS_KEY);
    if (!raw) {
      return {};
    }
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
};

const saveUserPrefs = () => {
  localStorage.setItem(
    USER_PREFS_KEY,
    JSON.stringify({
      year: state.year,
      category: state.category,
      sort: state.sort
    })
  );
};

const userPrefs = loadUserPrefs();
if (typeof userPrefs.year === 'number') {
  state.year = userPrefs.year;
}
if (typeof userPrefs.category === 'string') {
  state.category = userPrefs.category;
}
if (userPrefs.sort === 'title' || userPrefs.sort === 'nominations') {
  state.sort = userPrefs.sort;
}
if (state.category === ALL_CATEGORIES) {
  state.category = DEFAULT_CATEGORY;
}

const localPickKey = (year, userKey) => `oscars:picks:${year}:${userKey}`;

const loadLocalPicks = () => {
  try {
    const raw = localStorage.getItem(localPickKey(state.year, state.userKey));
    if (!raw) {
      return {};
    }
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
};

const saveLocalPicks = (picksByCategory) => {
  localStorage.setItem(
    localPickKey(state.year, state.userKey),
    JSON.stringify(picksByCategory || {})
  );
};

const yearSelect = document.getElementById('yearSelect');
const yearControlLabel = document.getElementById('yearControl');
const categorySelect = document.getElementById('categorySelect');
const sortSelect = document.getElementById('sortSelect');
const sortWrap = document.getElementById('sortWrap');
const stats = document.getElementById('stats');
const filmList = document.getElementById('filmList');
const cardTemplate = document.getElementById('filmCardTemplate');
const seenProgressLabel = document.getElementById('seenProgressLabel');
const seenProgressCount = document.getElementById('seenProgressCount');
const seenProgressFill = document.getElementById('seenProgressFill');
const pickProgressWrap = document.getElementById('pickProgressWrap');
const pickProgressLabel = document.getElementById('pickProgressLabel');
const pickProgressCount = document.getElementById('pickProgressCount');
const pickProgressFill = document.getElementById('pickProgressFill');
const compareProgressWrap = document.getElementById('compareProgressWrap');
const compareProgressLabel = document.getElementById('compareProgressLabel');
const compareProgressCount = document.getElementById('compareProgressCount');
const compareProgressFill = document.getElementById('compareProgressFill');
const announcementBanner = document.getElementById('announcementBanner');
const appHeader = document.querySelector('.app-header');
let liveSyncTimerId = null;
let liveSyncBusy = false;

const stableObjectSignature = (obj) =>
  JSON.stringify(
    Object.entries(obj || {}).sort((a, b) => String(a[0]).localeCompare(String(b[0])))
  );

const watchStateSignature = () =>
  JSON.stringify(
    [...(state.films || [])]
      .map((film) => [film.id, Boolean(film.freeToWatch), String(film.whereToWatchUrl || '')])
      .sort((a, b) => String(a[0]).localeCompare(String(b[0])))
  );

const liveSyncSignature = () =>
  `${stableObjectSignature(state.winnersByCategory)}|${String(state.votingLocked)}|${watchStateSignature()}|${JSON.stringify(state.banner || {})}|${JSON.stringify(state.performance || {})}`;

const api = async (path, options = {}) => {
  const response = await fetch(path, options);
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
  state.votingLocked = Boolean(payload.votingLocked);
  state.eventMode = Boolean(payload.eventMode);
  state.banner = payload.banner || { enabled: true, text: '' };
};

const loadSeen = async () => {
  const payload = await api(
    `/api/user-state?year=${state.year}&userKey=${encodeURIComponent(state.userKey)}`
  );
  state.seenFilmIds = new Set(payload.seenFilmIds || []);
  state.picksByCategory = { ...loadLocalPicks(), ...(payload.picksByCategory || {}) };
  state.performance = payload.performance || {
    winnerCategoryCount: 0,
    userCorrectCount: 0,
    betterThanPercent: 0,
    comparedUserCount: 0,
    rankPosition: 1,
    rankedUserCount: 0,
    tiedUserCount: 1
  };
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
  const presentByName = new Map(state.categories.map((category) => [category.name, category]));
  const ordered = [];
  for (const name of CATEGORY_VIEW_ORDER) {
    if (presentByName.has(name)) {
      ordered.push(presentByName.get(name));
      presentByName.delete(name);
    }
  }
  ordered.push(...presentByName.values());

  for (const category of ordered) {
    const option = document.createElement('option');
    option.value = category.name;
    option.textContent = category.name;
    categorySelect.append(option);
  }

  const all = document.createElement('option');
  all.value = ALL_CATEGORIES;
  all.textContent = 'All films';
  categorySelect.append(all);

  const hasCategory =
    state.category === ALL_CATEGORIES || state.categories.some((c) => c.name === state.category);
  if (!hasCategory) {
    state.category = state.categories.some((c) => c.name === DEFAULT_CATEGORY)
      ? DEFAULT_CATEGORY
      : (state.categories[0]?.name || ALL_CATEGORIES);
  }
  categorySelect.value = state.category;
  sizeSelectToOptions(categorySelect);
};

const renderStats = () => {
  const seenCount = state.films.filter((film) => state.seenFilmIds.has(film.id)).length;
  if (state.category === ALL_CATEGORIES) {
    stats.textContent = `You have seen ${seenCount} of ${state.films.length} nominated films`;
    return;
  }
  stats.textContent = `You have seen ${seenCount} of ${state.films.length} ${state.category} nominees`;
};

const renderProgress = () => {
  const yearFilmIds = new Set(state.nominations.map((n) => n.filmId));
  const total = yearFilmIds.size;
  let seen = 0;
  for (const filmId of state.seenFilmIds) {
    if (yearFilmIds.has(filmId)) {
      seen += 1;
    }
  }
  const percent = total ? Math.round((seen / total) * 100) : 0;
  seenProgressLabel.textContent = `${percent}% Seen`;
  seenProgressCount.textContent = `${seen} / ${total}`;
  seenProgressFill.style.width = `${percent}%`;

  const winnerEntries = Object.entries(state.winnersByCategory || {});
  if (winnerEntries.length === 0) {
    pickProgressWrap.hidden = true;
    compareProgressWrap.hidden = true;
    return;
  }

  let correct = 0;
  for (const [category, winnerFilmId] of winnerEntries) {
    if (state.picksByCategory?.[category] === winnerFilmId) {
      correct += 1;
    }
  }
  const picksPercent = Math.round((correct / winnerEntries.length) * 100);
  pickProgressWrap.hidden = false;
  pickProgressLabel.textContent = `${picksPercent}% Pick Accuracy`;
  pickProgressCount.textContent = `${correct} / ${winnerEntries.length}`;
  pickProgressFill.style.width = `${picksPercent}%`;

  const rankPosition = Number(state.performance?.rankPosition || 1);
  const rankedUserCount = Number(state.performance?.rankedUserCount || 0);
  const tiedUserCount = Number(state.performance?.tiedUserCount || 1);
  const normalizedRank = rankedUserCount > 1
    ? Math.round(((rankedUserCount - rankPosition) / (rankedUserCount - 1)) * 100)
    : 100;
  compareProgressWrap.hidden = false;
  compareProgressLabel.textContent = tiedUserCount > 1
    ? `Tied for #${rankPosition} of ${Math.max(rankedUserCount, 1)} Users`
    : `Rank #${rankPosition} of ${Math.max(rankedUserCount, 1)} Users`;
  compareProgressCount.textContent = 'Leaderboard';
  compareProgressFill.style.width = `${Math.max(0, Math.min(100, normalizedRank))}%`;
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
  renderProgress();
  filmList.innerHTML = '';

  for (const film of sortedFilms()) {
    const card = cardTemplate.content.firstElementChild.cloneNode(true);
    const nominatedIn = state.nominations.filter((n) => n.filmId === film.id);
    const categoryNames = unique(nominatedIn.map((n) => n.category));
    const seen = state.seenFilmIds.has(film.id);

    card.classList.toggle('seen-true', seen);
    const seenButton = card.querySelector('.seen-button');
    seenButton.dataset.filmId = film.id;
    seenButton.setAttribute('aria-pressed', seen ? 'true' : 'false');
    seenButton.textContent = seen ? 'Seen ✅' : 'Seen?';

    const pickButton = card.querySelector('.pick-button');
    const pickHint = card.querySelector('.pick-hint');
    const winnerLabel = card.querySelector('.winner-label');
    if (state.category !== ALL_CATEGORIES) {
      const category = state.category;
      const pickedFilmId = state.picksByCategory?.[category];
      const winnerFilmId = state.winnersByCategory?.[category];
      const locked = Boolean(state.votingLocked);
      const picked = pickedFilmId === film.id;
      const isWinner = winnerFilmId === film.id;

      pickButton.hidden = locked && !picked;
      pickButton.dataset.filmId = film.id;
      pickButton.dataset.category = category;
      pickButton.dataset.locked = locked ? 'true' : 'false';
      pickButton.dataset.pickResult = 'pending';
      pickButton.disabled = locked;
      pickButton.setAttribute('aria-pressed', picked ? 'true' : 'false');
      if (picked && winnerFilmId) {
        pickButton.dataset.pickResult = isWinner ? 'correct' : 'incorrect';
      }
      const pickedSuffix =
        picked && winnerFilmId && !isWinner ? ' ❌' : (picked ? ' ✅' : '');
      pickButton.textContent = locked
        ? `🔒 My Pick${pickedSuffix}`
        : `My Pick${pickedSuffix}`;

      winnerLabel.hidden = !isWinner;
      pickHint.hidden = true;
    } else {
      pickButton.hidden = true;
      pickButton.disabled = false;
      pickButton.dataset.pickResult = 'pending';
      winnerLabel.hidden = true;
      pickHint.hidden = false;
    }

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

    card.querySelector('.film-title').textContent = film.title;

    const meta = card.querySelector('.film-meta');
    if (state.category === ALL_CATEGORIES) {
      meta.textContent = `${categoryNames.length} Nomination${categoryNames.length === 1 ? '' : 's'}`;
    } else {
      const nominees = nominatedIn
        .filter((n) => n.category === state.category)
        .map((n) => n.nominee)
        .filter(Boolean);
      meta.textContent = nominees.length
        ? nominees.join(' • ')
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

    filmList.append(card);
  }
};

const renderBanner = () => {
  if (!announcementBanner) {
    return;
  }
  const banner = state.banner || {};
  const text = String(banner.text || '').trim();
  announcementBanner.hidden = !banner.enabled || !text;
  announcementBanner.textContent = text;
};

const render = () => {
  buildYearOptions();
  buildCategoryOptions();
  renderBanner();
  renderFilms();
};

const refresh = async () => {
  await loadNominees();
  await loadSeen();
  saveUserPrefs();
  startLiveSync();
  render();
};

const updateSeen = async (filmId, seen) => {
  await api('/api/user-state', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ year: state.year, userKey: state.userKey, filmId, seen })
  });
};

const updatePick = async (category, filmId, picked) => {
  saveLocalPicks(state.picksByCategory);
  await api('/api/user-pick', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ year: state.year, userKey: state.userKey, category, filmId, picked })
  });
};

const wireEvents = () => {
  yearSelect.addEventListener('change', async (event) => {
    state.year = Number(event.target.value);
    state.category = DEFAULT_CATEGORY;
    saveUserPrefs();
    await refresh();
  });

  categorySelect.addEventListener('change', async (event) => {
    state.category = event.target.value;
    saveUserPrefs();
    await refresh();
  });

  sortSelect.addEventListener('change', () => {
    state.sort = sortSelect.value;
    saveUserPrefs();
    renderFilms();
  });

  filmList.addEventListener('click', async (event) => {
    const seenButton = event.target.closest('.seen-button');
    if (seenButton) {
      const filmId = seenButton.dataset.filmId;
      const nextSeen = !state.seenFilmIds.has(filmId);
      await updateSeen(filmId, nextSeen);
      if (nextSeen) {
        state.seenFilmIds.add(filmId);
      } else {
        state.seenFilmIds.delete(filmId);
      }
      renderFilms();
      return;
    }

    const pickButton = event.target.closest('.pick-button');
    if (pickButton) {
      if (pickButton.dataset.locked === 'true') {
        return;
      }
      const category = pickButton.dataset.category;
      const filmId = pickButton.dataset.filmId;
      const currentlyPicked = state.picksByCategory?.[category] === filmId;
      const nextPicked = !currentlyPicked;

      if (currentlyPicked) {
        delete state.picksByCategory[category];
      } else {
        state.picksByCategory[category] = filmId;
      }
      renderFilms();

      try {
        await updatePick(category, filmId, nextPicked);
      } catch (error) {
        if (currentlyPicked) {
          state.picksByCategory[category] = filmId;
        } else {
          delete state.picksByCategory[category];
        }
        renderFilms();
        const message = String(error?.message || '');
        if (message.includes('API error 403: /api/user-pick')) {
          alert('Voting for this category is closed.');
        } else {
          alert(`Unable to save My Pick. ${message}`);
        }
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
    saveUserPrefs();
    refresh();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });

  window.addEventListener('storage', async (event) => {
    if (event.key !== EVENT_MODE_SIGNAL_KEY || !event.newValue) {
      return;
    }
    try {
      const payload = JSON.parse(event.newValue);
      if (!payload || Number(payload.year) !== Number(state.year)) {
        return;
      }
      state.eventMode = Boolean(payload.enabled);
      startLiveSync();
      await refresh();
    } catch {
      // Ignore malformed storage signal payloads.
    }
  });
};

const startLiveSync = () => {
  if (liveSyncTimerId) {
    clearInterval(liveSyncTimerId);
    liveSyncTimerId = null;
  }

  if (!state.eventMode) {
    return;
  }

  liveSyncTimerId = setInterval(async () => {
    if (liveSyncBusy || document.hidden) {
      return;
    }

    liveSyncBusy = true;
    const before = liveSyncSignature();
    try {
      await loadNominees();
      await loadSeen();
      renderBanner();
      const after = liveSyncSignature();
      if (after !== before) {
        renderFilms();
      }
    } catch {
      // Skip transient sync errors; normal manual actions still surface errors.
    } finally {
      liveSyncBusy = false;
    }
  }, LIVE_SYNC_INTERVAL_MS);
};

const start = async () => {
  await loadYears();
  await refresh();
  wireEvents();
};

start().catch((error) => {
  filmList.innerHTML = `<p>Failed to load app data: ${error.message}</p>`;
});
