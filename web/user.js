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
const APP_VERSION_CHECK_INTERVAL_MS = 60000;
const USER_PREFS_KEY = 'oscars:user:prefs';
const EVENT_MODE_SIGNAL_KEY = 'oscars:event-mode-signal';
const REPICK_NOTICE_KEY = 'oscars:repick-notice';
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
    viewingBetterThanPercent: 0,
    viewingComparedUserCount: 0,
    viewingRankPosition: 1,
    viewingRankedUserCount: 0,
    viewingTiedUserCount: 1,
    winnerCategoryCount: 0,
    userCorrectCount: 0,
    betterThanPercent: 0,
    comparedUserCount: 0,
    rankPosition: 1,
    rankedUserCount: 0,
    tiedUserCount: 1
  },
  category: ALL_CATEGORIES,
  categoryFilters: [],
  groupAllCategories: false,
  seenOnlyFilter: false,
  unseenOnlyFilter: false,
  sort: 'title',
  metricMode: 'viewing',
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

const hasStoredUserPrefs = () => Boolean(localStorage.getItem(USER_PREFS_KEY));

const saveUserPrefs = () => {
  localStorage.setItem(
    USER_PREFS_KEY,
    JSON.stringify({
      year: state.year,
      category: state.category,
      categoryFilters: state.categoryFilters,
      groupAllCategories: state.groupAllCategories,
      seenOnlyFilter: state.seenOnlyFilter,
      unseenOnlyFilter: state.unseenOnlyFilter,
      sort: state.sort,
      metricMode: state.metricMode
    })
  );
};

const userPrefs = loadUserPrefs();
const storedUserPrefsExist = hasStoredUserPrefs();
let metricModeExplicit = userPrefs.metricMode === 'viewing' || userPrefs.metricMode === 'picks';
if (typeof userPrefs.year === 'number') {
  state.year = userPrefs.year;
}
if (typeof userPrefs.category === 'string') {
  state.category = userPrefs.category;
}
if (Array.isArray(userPrefs.categoryFilters)) {
  state.categoryFilters = userPrefs.categoryFilters.filter((value) => typeof value === 'string');
}
if (typeof userPrefs.groupAllCategories === 'boolean') {
  state.groupAllCategories = userPrefs.groupAllCategories;
}
if (typeof userPrefs.seenOnlyFilter === 'boolean') {
  state.seenOnlyFilter = userPrefs.seenOnlyFilter;
}
if (typeof userPrefs.unseenOnlyFilter === 'boolean') {
  state.unseenOnlyFilter = userPrefs.unseenOnlyFilter;
}
if (userPrefs.sort === 'title' || userPrefs.sort === 'nominations') {
  state.sort = userPrefs.sort;
}
if (userPrefs.metricMode === 'viewing' || userPrefs.metricMode === 'picks') {
  state.metricMode = userPrefs.metricMode;
}
if (!Array.isArray(userPrefs.categoryFilters) && typeof userPrefs.category === 'string') {
  if (userPrefs.category !== ALL_CATEGORIES) {
    state.categoryFilters = [userPrefs.category];
  } else {
    state.categoryFilters = [];
  }
}
if (!storedUserPrefsExist) {
  state.category = ALL_CATEGORIES;
  state.categoryFilters = [];
  state.groupAllCategories = true;
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

const repickNoticeKey = (year, userKey) => `${REPICK_NOTICE_KEY}:${year}:${userKey}`;

const yearSelect = document.getElementById('yearSelect');
const yearControlLabel = document.getElementById('yearControl');
const categoryFilterDropdown = document.getElementById('categoryFilterDropdown');
const categoryFilterSummary = document.getElementById('categoryFilterSummary');
const categoryFilterOptions = document.getElementById('categoryFilterOptions');
const sortSelect = document.getElementById('sortSelect');
const sortWrap = document.getElementById('sortWrap');
const controlsSummary = document.getElementById('controlsSummary');
const filmList = document.getElementById('filmList');
const cardTemplate = document.getElementById('filmCardTemplate');
const seenProgressLabel = document.getElementById('seenProgressLabel');
const seenProgressCount = document.getElementById('seenProgressCount');
const seenProgressFill = document.getElementById('seenProgressFill');
const pickProgressWrap = document.getElementById('pickProgressWrap');
const pickProgressLabel = document.getElementById('pickProgressLabel');
const pickProgressCount = document.getElementById('pickProgressCount');
const pickProgressFill = document.getElementById('pickProgressFill');
const metricsToggle = document.getElementById('metricsToggle');
const metricModeButtons = [...document.querySelectorAll('[data-metric-mode]')];
const compareProgressWrap = document.getElementById('compareProgressWrap');
const compareProgressLabel = document.getElementById('compareProgressLabel');
const compareProgressCount = document.getElementById('compareProgressCount');
const compareProgressFill = document.getElementById('compareProgressFill');
const announcementBanner = document.getElementById('announcementBanner');
const siteModal = document.getElementById('siteModal');
const siteModalEyebrow = document.getElementById('siteModalEyebrow');
const siteModalTitle = document.getElementById('siteModalTitle');
const siteModalMessage = document.getElementById('siteModalMessage');
const siteModalButton = document.getElementById('siteModalButton');
const appHeader = document.querySelector('.app-header');
const currentBuildVersion = document
  .querySelector('meta[name="app-build-version"]')
  ?.getAttribute('content') || 'dev';
let liveSyncTimerId = null;
let appVersionTimerId = null;
let liveSyncBusy = false;
let activeModalClose = null;
let updatePromptShown = false;

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

const showSiteModal = ({
  eyebrow = 'Tracker Update',
  title = 'Action Needed',
  message = '',
  buttonLabel = 'OK'
}) => {
  if (!siteModal || !siteModalEyebrow || !siteModalTitle || !siteModalMessage || !siteModalButton) {
    window.alert(message || title);
    return Promise.resolve();
  }

  siteModalEyebrow.textContent = eyebrow;
  siteModalTitle.textContent = title;
  siteModalMessage.textContent = message;
  siteModalButton.textContent = buttonLabel;
  siteModal.hidden = false;
  document.body.style.overflow = 'hidden';

  return new Promise((resolve) => {
    const close = () => {
      siteModal.hidden = true;
      document.body.style.overflow = '';
      if (activeModalClose === close) {
        activeModalClose = null;
      }
      resolve();
    };
    activeModalClose = close;
    siteModalButton.focus();
  });
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
    `/api/nominees?year=${state.year}&category=${encodeURIComponent(ALL_CATEGORIES)}`
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
  const repickCategories = Array.isArray(payload.repickCategories)
    ? payload.repickCategories.filter((value) => typeof value === 'string' && value.trim())
    : [];
  const localPicks = { ...loadLocalPicks() };
  for (const category of repickCategories) {
    delete localPicks[category];
  }
  state.picksByCategory = { ...localPicks, ...(payload.picksByCategory || {}) };
  saveLocalPicks(state.picksByCategory);
  const repickSignature = JSON.stringify([...repickCategories].sort());
  const priorRepickSignature = localStorage.getItem(repickNoticeKey(state.year, state.userKey)) || '[]';
  if (repickCategories.length && repickSignature !== priorRepickSignature) {
    const categoryList = repickCategories.length === 2
      ? `${repickCategories[0]} and ${repickCategories[1]}`
      : repickCategories.join(', ');
    showSiteModal({
      eyebrow: 'Ballot Update',
      title: 'Please Pick Again',
      message: `Your previous pick${repickCategories.length === 1 ? '' : 's'} in ${categoryList} need${repickCategories.length === 1 ? 's' : ''} to be selected again.`,
      buttonLabel: 'Continue'
    });
  }
  localStorage.setItem(repickNoticeKey(state.year, state.userKey), repickSignature);
  state.performance = payload.performance || {
    viewingBetterThanPercent: 0,
    viewingComparedUserCount: 0,
    viewingRankPosition: 1,
    viewingRankedUserCount: 0,
    viewingTiedUserCount: 1,
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

const selectedCategories = () => {
  const categorySet = new Set(state.categories.map((category) => category.name));
  return state.categoryFilters.filter((name) => categorySet.has(name));
};

const updateCategoryFilterSummary = () => {
  const selected = selectedCategories();
  const parts = [];
  if (state.seenOnlyFilter && !state.unseenOnlyFilter) {
    parts.push('Seen');
  } else if (state.unseenOnlyFilter && !state.seenOnlyFilter) {
    parts.push('Unseen');
  } else if (state.seenOnlyFilter && state.unseenOnlyFilter) {
    parts.push('Seen + Unseen');
  }
  if (state.groupAllCategories) {
    parts.push('All categories');
  } else if (selected.length === 0) {
    parts.push('All films');
  } else if (selected.length === 1) {
    parts.push(selected[0]);
  } else {
    parts.push(`${selected.length} categories`);
  }
  categoryFilterSummary.textContent = parts.join(' • ');
};

const buildCategoryOptions = () => {
  categoryFilterOptions.innerHTML = '';
  const ordered = [...state.categories].sort((a, b) => a.name.localeCompare(b.name));

  state.categoryFilters = selectedCategories();

  const addOption = (value, text, checked) => {
    const label = document.createElement('label');
    label.className = 'category-filter-option';
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.value = value;
    input.checked = checked;
    input.dataset.filterType = value === '__SEEN__' || value === '__UNSEEN__' ? 'state' : 'category';
    const span = document.createElement('span');
    span.textContent = text;
    label.append(input, span);
    categoryFilterOptions.append(label);
  };

  addOption('__SEEN__', 'Seen', state.seenOnlyFilter);
  addOption('__UNSEEN__', 'Unseen', state.unseenOnlyFilter);
  addOption('__GROUP_ALL__', 'All Categories', state.groupAllCategories);

  const divider = document.createElement('div');
  divider.className = 'category-filter-divider';
  categoryFilterOptions.append(divider);

  const selectedSet = new Set(state.categoryFilters);
  for (const category of ordered) {
    addOption(category.name, category.name, selectedSet.has(category.name));
  }
  updateCategoryFilterSummary();
};

const categoryOrderIndex = new Map(CATEGORY_VIEW_ORDER.map((name, idx) => [name, idx]));

const compareFilms = (nominationCounts) => (a, b) => {
  if (state.sort === 'nominations') {
    const countA = nominationCounts.get(a.id) || 0;
    const countB = nominationCounts.get(b.id) || 0;
    if (countB !== countA) {
      return countB - countA;
    }
  }
  return a.title.localeCompare(b.title);
};

const passesSeenFilters = (filmId) => {
  const seen = state.seenFilmIds.has(filmId);
  if (state.seenOnlyFilter && !state.unseenOnlyFilter) {
    return seen;
  }
  if (state.unseenOnlyFilter && !state.seenOnlyFilter) {
    return !seen;
  }
  return true;
};

const categoryNominationCounts = () => {
  const byCategory = new Map();
  for (const nomination of state.nominations) {
    const map = byCategory.get(nomination.category) || new Map();
    map.set(nomination.filmId, (map.get(nomination.filmId) || 0) + 1);
    byCategory.set(nomination.category, map);
  }
  return byCategory;
};

const selectedCategoriesInOrder = () => {
  if (state.groupAllCategories) {
    return state.categories
      .map((category) => category.name)
      .sort((a, b) => {
        const ai = categoryOrderIndex.has(a) ? categoryOrderIndex.get(a) : Number.MAX_SAFE_INTEGER;
        const bi = categoryOrderIndex.has(b) ? categoryOrderIndex.get(b) : Number.MAX_SAFE_INTEGER;
        if (ai !== bi) {
          return ai - bi;
        }
        return a.localeCompare(b);
      });
  }
  const selected = selectedCategories();
  if (!selected.length) {
    return [];
  }
  return [...selected].sort((a, b) => {
    const ai = categoryOrderIndex.has(a) ? categoryOrderIndex.get(a) : Number.MAX_SAFE_INTEGER;
    const bi = categoryOrderIndex.has(b) ? categoryOrderIndex.get(b) : Number.MAX_SAFE_INTEGER;
    if (ai !== bi) {
      return ai - bi;
    }
    return a.localeCompare(b);
  });
};

const buildDisplayGroups = () => {
  const selected = selectedCategoriesInOrder();
  const allCounts = new Map();
  for (const nomination of state.nominations) {
    allCounts.set(nomination.filmId, (allCounts.get(nomination.filmId) || 0) + 1);
  }

  if (!selected.length) {
    const rows = state.films
      .filter((film) => passesSeenFilters(film.id))
      .sort(compareFilms(allCounts))
      .map((film) => ({ film, contextCategory: '' }));
    return [{ category: '', rows }];
  }

  const countsByCategory = categoryNominationCounts();
  const groups = [];
  for (const category of selected) {
    const nominatedRows = state.nominations.filter((n) => n.category === category);
    const counts = countsByCategory.get(category) || new Map();
    const rows = nominatedRows
      .map((nomination) => ({
        nomination,
        film: state.films.find((film) => film.id === nomination.filmId),
        contextCategory: category
      }))
      .filter((row) => row.film)
      .filter((row) => passesSeenFilters(row.film.id))
      .sort((a, b) => {
        const byFilm = compareFilms(counts)(a.film, b.film);
        if (byFilm !== 0) {
          return byFilm;
        }
        return String(a.nomination.nominee || '').localeCompare(String(b.nomination.nominee || ''));
      });
    groups.push({ category, rows });
  }
  return groups;
};

const renderStats = (groups) => {
  if (!controlsSummary) {
    return;
  }
  const selected = selectedCategoriesInOrder();
  const uniqueFilmIds = new Set();
  const uniqueSeenFilmIds = new Set();
  for (const group of groups) {
    for (const row of group.rows) {
      uniqueFilmIds.add(row.film.id);
      if (state.seenFilmIds.has(row.film.id)) {
        uniqueSeenFilmIds.add(row.film.id);
      }
    }
  }
  const rowCount = uniqueFilmIds.size;
  const seenCount = uniqueSeenFilmIds.size;
  if (selected.length === 1 && !state.seenOnlyFilter && !state.unseenOnlyFilter) {
    const category = selected[0];
    const categoryRows = state.nominations.filter((n) => n.category === category);
    const filteredRows = categoryRows.filter((n) => passesSeenFilters(n.filmId));
    const categorySeenCount = filteredRows.filter((n) => state.seenFilmIds.has(n.filmId)).length;
    controlsSummary.textContent = `You have seen ${categorySeenCount} of ${filteredRows.length} ${selected[0]} nominees`;
    return;
  }
  if (!state.groupAllCategories && selected.length === 0 && !state.seenOnlyFilter && !state.unseenOnlyFilter) {
    controlsSummary.textContent = `You have seen ${seenCount} of ${rowCount} nominated films`;
    return;
  }
  controlsSummary.textContent = `You have seen ${seenCount} of ${rowCount} films in this view`;
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

  const activeMetricMode = state.eventMode
    ? (metricModeExplicit ? state.metricMode : 'picks')
    : 'viewing';
  metricsToggle.hidden = !state.eventMode;
  for (const button of metricModeButtons) {
    const active = button.dataset.metricMode === activeMetricMode;
    button.setAttribute('aria-pressed', active ? 'true' : 'false');
  }

  const renderViewingComparison = () => {
    if (seen > 0) {
      const viewingPercent = Math.max(
        0,
        Math.min(100, Number(state.performance?.viewingBetterThanPercent || 0))
      );
      const viewingRankPosition = Number(state.performance?.viewingRankPosition || 1);
      const viewingRankedUserCount = Number(state.performance?.viewingRankedUserCount || 0);
      const viewingTiedUserCount = Number(state.performance?.viewingTiedUserCount || 1);
      compareProgressWrap.hidden = false;
      compareProgressLabel.textContent = `You’ve seen more than ${viewingPercent}% of users`;
      compareProgressCount.textContent = viewingTiedUserCount > 1
        ? `Tied #${viewingRankPosition}/${Math.max(viewingRankedUserCount, 1)}`
        : `Rank #${viewingRankPosition}/${Math.max(viewingRankedUserCount, 1)}`;
      compareProgressFill.style.width = `${viewingPercent}%`;
    } else {
      compareProgressWrap.hidden = true;
    }
  };

  if (activeMetricMode === 'viewing') {
    pickProgressWrap.hidden = true;
    renderViewingComparison();
    return;
  }

  const winnerEntries = Object.entries(state.winnersByCategory || {});
  if (winnerEntries.length === 0) {
    pickProgressWrap.hidden = true;
    compareProgressWrap.hidden = true;
    return;
  }

  let correct = 0;
  for (const [category, winnerNominationId] of winnerEntries) {
    if (Number(state.picksByCategory?.[category] || 0) === Number(winnerNominationId || 0)) {
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

const renderFilms = () => {
  const selected = selectedCategoriesInOrder();
  const showSort = !state.groupAllCategories && selected.length === 0;
  sortWrap.hidden = !showSort;
  sortSelect.value = state.sort;
  sizeSelectToOptions(sortSelect);

  const groups = buildDisplayGroups();
  renderStats(groups);
  renderProgress();
  filmList.innerHTML = '';

  const multiCategoryMode = selected.length > 1;
  for (const group of groups) {
    if (group.rows.length === 0) {
      continue;
    }
    if (multiCategoryMode) {
      const header = document.createElement('h3');
      header.className = 'film-group-header';
      header.textContent = group.category;
      filmList.append(header);
    }

    for (const row of group.rows) {
      const film = row.film;
      const contextCategory = row.contextCategory;
      const selectedNomination = row.nomination || null;
      const card = cardTemplate.content.firstElementChild.cloneNode(true);
      const nominatedIn = state.nominations.filter((n) => n.filmId === film.id);
      const categoryNames = unique(nominatedIn.map((n) => n.category));
      const nominationCount = nominatedIn.length;
      const seen = state.seenFilmIds.has(film.id);

      card.classList.toggle('seen-true', seen);
      const seenButton = card.querySelector('.seen-button');
      seenButton.dataset.filmId = film.id;
      seenButton.setAttribute('aria-pressed', seen ? 'true' : 'false');
      seenButton.textContent = seen ? 'Seen ✅' : 'Seen?';

      const pickButton = card.querySelector('.pick-button');
      const pickHint = card.querySelector('.pick-hint');
      const winnerLabel = card.querySelector('.winner-label');
      const singleCategory = contextCategory || '';
      if (singleCategory) {
        const category = singleCategory;
        const nominationId = Number(selectedNomination?.nominationId || 0);
        const pickedNominationId = Number(state.picksByCategory?.[category] || 0);
        const winnerNominationId = Number(state.winnersByCategory?.[category] || 0);
        const locked = Boolean(state.votingLocked);
        const picked = pickedNominationId === nominationId;
        const isWinner = winnerNominationId === nominationId;

        pickButton.hidden = locked && !picked;
        pickButton.dataset.filmId = film.id;
        pickButton.dataset.nominationId = String(nominationId);
        pickButton.dataset.category = category;
        pickButton.dataset.locked = locked ? 'true' : 'false';
        pickButton.dataset.pickResult = 'pending';
        pickButton.disabled = locked;
        pickButton.setAttribute('aria-pressed', picked ? 'true' : 'false');
        if (picked && winnerNominationId) {
          pickButton.dataset.pickResult = isWinner ? 'correct' : 'incorrect';
        }
        const pickedSuffix =
          picked && winnerNominationId && !isWinner ? ' ❌' : (picked ? ' ✅' : '');
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
      if (!singleCategory) {
        meta.textContent = `${nominationCount} Nomination${nominationCount === 1 ? '' : 's'}`;
      } else {
        meta.textContent = selectedNomination?.nominee || 'Nominee details unavailable.';
      }

      const tags = card.querySelector('.tags');
      const showCategoryTags = !singleCategory && !state.groupAllCategories && selected.length === 0;
      if (showCategoryTags) {
        for (const name of categoryNames) {
          const link = document.createElement('button');
          link.type = 'button';
          link.className = 'tag category-link';
          link.dataset.category = name;
          link.textContent = name;
          tags.append(link);
        }
      } else {
        tags.hidden = true;
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

const updatePick = async (category, filmId, nominationId, picked) => {
  saveLocalPicks(state.picksByCategory);
  await api('/api/user-pick', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ year: state.year, userKey: state.userKey, category, filmId, nominationId, picked })
  });
};

const wireEvents = () => {
  yearSelect.addEventListener('change', async (event) => {
    state.year = Number(event.target.value);
    state.category = ALL_CATEGORIES;
    state.categoryFilters = [];
    state.groupAllCategories = false;
    state.seenOnlyFilter = false;
    state.unseenOnlyFilter = false;
    saveUserPrefs();
    await refresh();
  });

  sortSelect.addEventListener('change', () => {
    state.sort = sortSelect.value;
    saveUserPrefs();
    renderFilms();
  });

  metricModeButtons.forEach((button) => {
    button.addEventListener('click', () => {
      const nextMode = button.dataset.metricMode;
      if (nextMode !== 'viewing' && nextMode !== 'picks') {
        return;
      }
      state.metricMode = nextMode;
      metricModeExplicit = true;
      saveUserPrefs();
      renderProgress();
    });
  });

  if (siteModal) {
    siteModal.addEventListener('click', (event) => {
      if (!event.target.closest('.site-modal-dialog') && activeModalClose) {
        activeModalClose();
      }
      if (event.target.closest('[data-modal-close]') && activeModalClose) {
        activeModalClose();
      }
    });
  }
  if (siteModalButton) {
    siteModalButton.addEventListener('click', () => {
      if (activeModalClose) {
        activeModalClose();
      }
    });
  }
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && activeModalClose && siteModal && !siteModal.hidden) {
      activeModalClose();
    }
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
      const nominationId = Number(pickButton.dataset.nominationId || 0);
      const currentlyPicked = Number(state.picksByCategory?.[category] || 0) === nominationId;
      const nextPicked = !currentlyPicked;

      if (currentlyPicked) {
        delete state.picksByCategory[category];
      } else {
        state.picksByCategory[category] = nominationId;
      }
      renderFilms();

      try {
        await updatePick(category, filmId, nominationId, nextPicked);
      } catch (error) {
        if (currentlyPicked) {
          state.picksByCategory[category] = nominationId;
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
    state.categoryFilters = [nextCategory];
    state.groupAllCategories = false;
    state.seenOnlyFilter = false;
    state.unseenOnlyFilter = false;
    buildCategoryOptions();
    saveUserPrefs();
    renderFilms();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });

  categoryFilterOptions.addEventListener('change', (event) => {
    const input = event.target.closest('input[type="checkbox"]');
    if (!input) {
      return;
    }
    if (input.value === '__SEEN__') {
      state.seenOnlyFilter = input.checked;
    } else if (input.value === '__UNSEEN__') {
      state.unseenOnlyFilter = input.checked;
    } else if (input.value === '__GROUP_ALL__') {
      state.groupAllCategories = input.checked;
      if (input.checked) {
        state.categoryFilters = [];
      }
    } else {
      if (state.groupAllCategories && input.checked) {
        state.groupAllCategories = false;
      }
      const next = new Set(selectedCategories());
      if (input.checked) {
        next.add(input.value);
      } else {
        next.delete(input.value);
      }
      state.categoryFilters = [...next];
    }
    buildCategoryOptions();
    saveUserPrefs();
    renderFilms();
  });

  document.addEventListener('click', (event) => {
    if (!categoryFilterDropdown.open) {
      return;
    }
    if (categoryFilterDropdown.contains(event.target)) {
      return;
    }
    categoryFilterDropdown.open = false;
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

const maybeOpenPreviewModal = async () => {
  const params = new URLSearchParams(window.location.search);
  if (params.get('previewRepickModal') !== '1') {
    return;
  }
  await showSiteModal({
    eyebrow: 'Ballot Update',
    title: 'Please Pick Again',
    message: 'Your previous pick in Actor in a Supporting Role needs to be selected again.',
    buttonLabel: 'Continue'
  });
};

const startAppVersionCheck = () => {
  if (appVersionTimerId) {
    clearInterval(appVersionTimerId);
    appVersionTimerId = null;
  }

  appVersionTimerId = setInterval(async () => {
    if (document.hidden || updatePromptShown || activeModalClose) {
      return;
    }
    try {
      const payload = await api('/api/app-version');
      const nextVersion = String(payload?.version || '').trim();
      if (!nextVersion || nextVersion === currentBuildVersion) {
        return;
      }
      updatePromptShown = true;
      await showSiteModal({
        eyebrow: 'Update Available',
        title: 'Refresh for the Latest Version',
        message: 'A new version of whatsnominated is ready. Refresh now to get the latest fixes and ballot updates.',
        buttonLabel: 'Refresh Now'
      });
      window.location.reload();
    } catch {
      // Skip transient version check failures.
    }
  }, APP_VERSION_CHECK_INTERVAL_MS);
};

const start = async () => {
  await loadYears();
  await refresh();
  wireEvents();
  await maybeOpenPreviewModal();
  startAppVersionCheck();
};

start().catch((error) => {
  filmList.innerHTML = `<p>Failed to load app data: ${error.message}</p>`;
});
