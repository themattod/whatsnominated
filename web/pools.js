const state = {
  session: { loggedIn: false, csrfToken: '', user: null },
  years: [],
  year: null,
  pools: [],
  selectedPoolId: '',
  selectedPool: null,
  globalPickRows: [],
  globalPicksByCategoryId: {},
  poolPicksRows: [],
  poolEffectiveByCategoryId: {},
  poolOverrideByCategoryId: {},
  categoriesByName: [],
  nomineesByCategoryName: new Map(),
  filmsById: new Map(),
  submissionStatus: null,
  leaderboard: [],
  members: [],
  results: [],
  invites: [],
  toastTimer: null
};

const authStatus = document.getElementById('authStatus');
const authLoggedOut = document.getElementById('authLoggedOut');
const authLoggedIn = document.getElementById('authLoggedIn');
const authUserLabel = document.getElementById('authUserLabel');
const loginForm = document.getElementById('loginForm');
const registerForm = document.getElementById('registerForm');
const logoutButton = document.getElementById('logoutButton');
const yearSelect = document.getElementById('yearSelect');
const poolSelect = document.getElementById('poolSelect');
const refreshPoolsButton = document.getElementById('refreshPoolsButton');
const createPoolForm = document.getElementById('createPoolForm');
const newPoolDescription = document.getElementById('newPoolDescription');
const newPoolScoringMode = document.getElementById('newPoolScoringMode');
const newPoolEntryMode = document.getElementById('newPoolEntryMode');
const newPoolEntryFeeWrap = document.getElementById('newPoolEntryFeeWrap');
const newPoolEntryFee = document.getElementById('newPoolEntryFee');
const newPoolInvitePolicy = document.getElementById('newPoolInvitePolicy');
const newPoolTiebreakerQuestion = document.getElementById('newPoolTiebreakerQuestion');
const newPoolPaymentRequiredToScore = document.getElementById('newPoolPaymentRequiredToScore');
const newPoolAllowOverrides = document.getElementById('newPoolAllowOverrides');
const poolMeta = document.getElementById('poolMeta');
const poolLinks = document.getElementById('poolLinks');
const poolSettingsForm = document.getElementById('poolSettingsForm');
const editPoolName = document.getElementById('editPoolName');
const editPoolDescription = document.getElementById('editPoolDescription');
const editPoolScoringMode = document.getElementById('editPoolScoringMode');
const editPoolEntryMode = document.getElementById('editPoolEntryMode');
const editPoolEntryFeeWrap = document.getElementById('editPoolEntryFeeWrap');
const editPoolEntryFee = document.getElementById('editPoolEntryFee');
const editPoolInvitePolicy = document.getElementById('editPoolInvitePolicy');
const editPoolTiebreakerQuestion = document.getElementById('editPoolTiebreakerQuestion');
const editPoolPaymentRequiredToScore = document.getElementById('editPoolPaymentRequiredToScore');
const editPoolAllowOverrides = document.getElementById('editPoolAllowOverrides');
const poolSettingsStatus = document.getElementById('poolSettingsStatus');
const globalPicksWrap = document.getElementById('globalPicksWrap');
const poolPicksWrap = document.getElementById('poolPicksWrap');
const submissionStatus = document.getElementById('submissionStatus');
const submitBallotForm = document.getElementById('submitBallotForm');
const submitBallotButton = document.getElementById('submitBallotButton');
const tiebreakerAnswer = document.getElementById('tiebreakerAnswer');
const leaderboardWrap = document.getElementById('leaderboardWrap');
const tieReviewWrap = document.getElementById('tieReviewWrap');
const membersWrap = document.getElementById('membersWrap');
const resultsWrap = document.getElementById('resultsWrap');
const inviteEmailForm = document.getElementById('inviteEmailForm');
const inviteEmailInput = document.getElementById('inviteEmailInput');
const createShareLinkButton = document.getElementById('createShareLinkButton');
const invitePermissionsNote = document.getElementById('invitePermissionsNote');
const invitesWrap = document.getElementById('invitesWrap');
const pageMessage = document.getElementById('pageMessage');
const toast = document.getElementById('toast');

const queryPoolId = new URLSearchParams(window.location.search).get('pool') || '';
if (queryPoolId) {
  state.selectedPoolId = queryPoolId;
}

const setMessage = (message, isError = false) => {
  pageMessage.textContent = message || '';
  pageMessage.classList.toggle('error-note', Boolean(message) && isError);
};

const showToast = (message, kind = 'ok') => {
  if (!toast) {
    return;
  }
  toast.textContent = message;
  toast.hidden = false;
  toast.classList.remove('error', 'ok');
  toast.classList.add(kind === 'error' ? 'error' : 'ok');
  if (state.toastTimer) {
    clearTimeout(state.toastTimer);
  }
  state.toastTimer = setTimeout(() => {
    toast.hidden = true;
    toast.textContent = '';
  }, 2600);
};

const api = async (path, options = {}) => {
  const headers = { ...(options.headers || {}) };
  if (options.method && options.method !== 'GET' && state.session.csrfToken) {
    headers['X-CSRF-Token'] = state.session.csrfToken;
  }
  const response = await fetch(path, { ...options, headers });
  const raw = await response.text();
  let payload;
  try {
    payload = raw ? JSON.parse(raw) : {};
  } catch {
    payload = { ok: false, error: raw || `HTTP ${response.status}` };
  }
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || `HTTP ${response.status}`);
  }
  return payload;
};

const clearPoolState = () => {
  state.selectedPool = null;
  state.poolPicksRows = [];
  state.poolEffectiveByCategoryId = {};
  state.poolOverrideByCategoryId = {};
  state.submissionStatus = null;
  state.leaderboard = [];
  state.members = [];
  state.results = [];
  state.invites = [];
};

const loadSession = async () => {
  const payload = await api('/api/auth/session');
  state.session.loggedIn = Boolean(payload.loggedIn);
  state.session.csrfToken = payload.csrfToken || '';
  state.session.user = payload.user || null;
};

const loadYears = async () => {
  const payload = await api('/api/years');
  state.years = payload.years || [];
  if (!state.year && state.years.length) {
    state.year = state.years[0].year;
  }
  if (state.years.length && !state.years.some((row) => row.year === state.year)) {
    state.year = state.years[0].year;
  }
};

const loadNominees = async () => {
  if (!state.year) {
    return;
  }
  const payload = await api(`/api/nominees?year=${encodeURIComponent(String(state.year))}&category=__ALL__`);
  state.categoriesByName = (payload.categories || []).map((row) => row.name).sort((a, b) => a.localeCompare(b));
  state.filmsById = new Map((payload.films || []).map((film) => [film.id, film]));
  state.nomineesByCategoryName = new Map();
  for (const nomination of payload.nominations || []) {
    const list = state.nomineesByCategoryName.get(nomination.category) || [];
    if (!list.some((row) => row.filmId === nomination.filmId)) {
      list.push({
        filmId: nomination.filmId,
        filmTitle: state.filmsById.get(nomination.filmId)?.title || nomination.filmId
      });
    }
    state.nomineesByCategoryName.set(nomination.category, list);
  }
  for (const [category, list] of state.nomineesByCategoryName.entries()) {
    list.sort((a, b) => a.filmTitle.localeCompare(b.filmTitle));
    state.nomineesByCategoryName.set(category, list);
  }
};

const loadPools = async () => {
  if (!state.session.loggedIn) {
    state.pools = [];
    state.selectedPoolId = '';
    clearPoolState();
    return;
  }
  const payload = await api(`/api/pools?year=${encodeURIComponent(String(state.year))}`);
  state.pools = payload.pools || [];
  if (!state.pools.some((pool) => pool.id === state.selectedPoolId)) {
    state.selectedPoolId = state.pools[0]?.id || '';
  }
  state.selectedPool = state.pools.find((pool) => pool.id === state.selectedPoolId) || null;
};

const loadGlobalPicks = async () => {
  if (!state.session.loggedIn || !state.year) {
    state.globalPickRows = [];
    state.globalPicksByCategoryId = {};
    return;
  }
  const payload = await api(`/api/picks/global?year=${encodeURIComponent(String(state.year))}`);
  state.globalPickRows = payload.picks || [];
  const map = {};
  for (const row of state.globalPickRows) {
    if (row.filmId) {
      map[String(row.categoryId)] = row.filmId;
    }
  }
  state.globalPicksByCategoryId = map;
};

const loadPoolData = async () => {
  if (!state.session.loggedIn || !state.selectedPoolId) {
    clearPoolState();
    return;
  }
  const [poolPayload, picksPayload, submissionPayload, leaderboardPayload, resultsPayload, membersPayload] = await Promise.all([
    api(`/api/pools/${encodeURIComponent(state.selectedPoolId)}`),
    api(`/api/pools/${encodeURIComponent(state.selectedPoolId)}/picks`),
    api(`/api/pools/${encodeURIComponent(state.selectedPoolId)}/submission-status`),
    api(`/api/pools/${encodeURIComponent(state.selectedPoolId)}/leaderboard`),
    api(`/api/pools/${encodeURIComponent(state.selectedPoolId)}/results`),
    api(`/api/pools/${encodeURIComponent(state.selectedPoolId)}/members`)
  ]);
  state.selectedPool = poolPayload.pool || state.selectedPool;
  state.poolPicksRows = picksPayload.picks || [];
  state.submissionStatus = submissionPayload;
  state.leaderboard = leaderboardPayload.leaderboard || [];
  state.members = membersPayload.members || [];
  state.results = resultsPayload.results || [];
  const effective = {};
  const override = {};
  for (const row of state.poolPicksRows) {
    if (row.filmId) {
      effective[String(row.categoryId)] = row.filmId;
    }
    if (row.source === 'override' && row.filmId) {
      override[String(row.categoryId)] = row.filmId;
    }
  }
  state.poolEffectiveByCategoryId = effective;
  state.poolOverrideByCategoryId = override;

  if (state.selectedPool?.memberRole === 'owner') {
    const invitesPayload = await api(`/api/pools/${encodeURIComponent(state.selectedPoolId)}/invites`);
    state.invites = invitesPayload.invites || [];
  } else {
    state.invites = [];
  }
};

const renderAuth = () => {
  authLoggedOut.hidden = state.session.loggedIn;
  authLoggedIn.hidden = !state.session.loggedIn;
  authStatus.textContent = state.session.loggedIn ? 'Signed in' : 'Not signed in';
  authUserLabel.textContent = state.session.loggedIn
    ? `${state.session.user?.displayName || ''} (${state.session.user?.email || ''})`
    : '';
};

const renderYears = () => {
  yearSelect.innerHTML = '';
  for (const year of state.years) {
    const option = document.createElement('option');
    option.value = String(year.year);
    option.textContent = String(year.year);
    yearSelect.append(option);
  }
  if (state.year) {
    yearSelect.value = String(state.year);
  }
};

const renderPools = () => {
  poolSelect.innerHTML = '';
  const first = document.createElement('option');
  first.value = '';
  first.textContent = state.session.loggedIn ? (state.pools.length ? 'Select a pool' : 'No pools yet') : 'Sign in to view pools';
  poolSelect.append(first);
  for (const pool of state.pools) {
    const option = document.createElement('option');
    option.value = pool.id;
    option.textContent = pool.name;
    poolSelect.append(option);
  }
  poolSelect.value = state.selectedPoolId || '';
  poolSelect.disabled = !state.session.loggedIn;
};

const filmTitle = (filmId) => state.filmsById.get(filmId)?.title || filmId || '—';

const pickSelect = ({ categoryName, selectedFilmId, includeGlobalOption = false, disabled, onChange }) => {
  const select = document.createElement('select');
  if (includeGlobalOption) {
    const option = document.createElement('option');
    option.value = '';
    option.textContent = 'Use global pick';
    select.append(option);
  } else {
    const option = document.createElement('option');
    option.value = '';
    option.textContent = 'Select a film';
    select.append(option);
  }
  for (const nominee of (state.nomineesByCategoryName.get(categoryName) || [])) {
    const option = document.createElement('option');
    option.value = nominee.filmId;
    option.textContent = nominee.filmTitle;
    select.append(option);
  }
  select.value = selectedFilmId || '';
  select.disabled = Boolean(disabled);
  select.addEventListener('change', onChange);
  return select;
};

const picksCard = ({ categoryLabel, select, effectiveText }) => {
  const card = document.createElement('article');
  card.className = 'pool-pick-card';
  const heading = document.createElement('h3');
  heading.textContent = categoryLabel;
  const bottom = document.createElement('div');
  bottom.className = 'small-note';
  bottom.textContent = effectiveText;
  card.append(heading, select, bottom);
  return card;
};

const renderGlobalPicks = () => {
  globalPicksWrap.innerHTML = '';
  if (!state.session.loggedIn) {
    globalPicksWrap.textContent = 'Sign in to set global picks.';
    return;
  }
  const grid = document.createElement('div');
  grid.className = 'pool-pick-grid';
  for (const row of state.globalPickRows) {
    const current = state.globalPicksByCategoryId[String(row.categoryId)] || '';
    const select = pickSelect({
      categoryName: row.category,
      selectedFilmId: current,
      includeGlobalOption: false,
      disabled: false,
      onChange: async () => {
        if (!select.value) {
          select.value = current;
          return;
        }
        try {
          await api('/api/picks/global', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ year: state.year, categoryId: row.categoryId, filmId: select.value })
          });
          showToast('Global pick saved.');
          await refreshAll();
        } catch (error) {
          showToast(`Save failed: ${error.message}`, 'error');
          select.value = current;
        }
      }
    });
    const card = picksCard({
      categoryLabel: row.category,
      select,
      effectiveText: current ? `Current: ${filmTitle(current)}` : 'Current: none'
    });
    grid.append(card);
  }
  globalPicksWrap.append(grid);
};

const renderPoolPicks = () => {
  poolPicksWrap.innerHTML = '';
  if (!state.session.loggedIn || !state.selectedPoolId) {
    poolPicksWrap.textContent = 'Select a pool to configure pool overrides.';
    return;
  }
  const locked = Boolean(state.selectedPool?.votingLocked);
  const overridesAllowed = Boolean(state.selectedPool?.allowPoolOverrides);
  const grid = document.createElement('div');
  grid.className = 'pool-pick-grid';

  for (const row of state.poolPicksRows) {
    const current = state.poolOverrideByCategoryId[String(row.categoryId)] || '';
    const effectiveId = state.poolEffectiveByCategoryId[String(row.categoryId)] || state.globalPicksByCategoryId[String(row.categoryId)] || '';
    const select = pickSelect({
      categoryName: row.category,
      selectedFilmId: current,
      includeGlobalOption: true,
      disabled: locked || !overridesAllowed,
      onChange: async () => {
        try {
          await api(`/api/pools/${encodeURIComponent(state.selectedPoolId)}/picks`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ categoryId: row.categoryId, filmId: select.value })
          });
          showToast('Pool override updated.');
          await refreshAll();
        } catch (error) {
          showToast(`Pool update failed: ${error.message}`, 'error');
          select.value = current;
        }
      }
    });
    const info = locked
      ? `Effective: ${filmTitle(effectiveId)} | Voting locked`
      : !overridesAllowed
        ? `Effective: ${filmTitle(effectiveId)} | Overrides disabled`
        : `Effective: ${filmTitle(effectiveId)}`;
    grid.append(picksCard({ categoryLabel: row.category, select, effectiveText: info }));
  }
  poolPicksWrap.append(grid);
};

const renderPoolMeta = () => {
  if (!state.selectedPool) {
    poolMeta.textContent = 'No pool selected.';
    poolLinks.textContent = '';
    return;
  }
  const pool = state.selectedPool;
  poolMeta.textContent = `${pool.name} | ${pool.memberRole} | scoring: ${pool.scoringMode} | status: ${pool.status} | voting ${pool.votingLocked ? 'locked' : 'open'}`;
  poolLinks.innerHTML = '';
  const publicLink = document.createElement('a');
  publicLink.href = `/pool-public.html?pool=${encodeURIComponent(pool.id)}`;
  publicLink.textContent = 'Open public leaderboard page';
  publicLink.target = '_blank';
  poolLinks.append(publicLink);
};

const toggleEntryFeeField = () => {
  const manualPayment = newPoolEntryMode?.value === 'manual_transfer';
  if (newPoolEntryFeeWrap) {
    newPoolEntryFeeWrap.hidden = !manualPayment;
  }
  if (!manualPayment && newPoolEntryFee) {
    newPoolEntryFee.value = '';
  }
};

const toggleEditEntryFeeField = () => {
  const manualPayment = editPoolEntryMode?.value === 'manual_transfer';
  if (editPoolEntryFeeWrap) {
    editPoolEntryFeeWrap.hidden = !manualPayment;
  }
  if (!manualPayment && editPoolEntryFee) {
    editPoolEntryFee.value = '';
  }
};

const renderPoolSettingsEditor = () => {
  const pool = state.selectedPool;
  const isOwner = pool?.memberRole === 'owner';
  if (!poolSettingsForm) {
    return;
  }
  poolSettingsForm.hidden = !pool || !isOwner;
  if (!pool || !isOwner) {
    if (poolSettingsStatus) {
      poolSettingsStatus.textContent = '';
      poolSettingsStatus.classList.remove('error-note');
    }
    return;
  }

  editPoolName.value = pool.name || '';
  editPoolDescription.value = pool.description || '';
  editPoolScoringMode.value = 'standard';
  editPoolEntryMode.value = pool.entryMode || 'none';
  editPoolInvitePolicy.value = pool.invitePolicy || 'both';
  editPoolTiebreakerQuestion.value = pool.tiebreakerQuestion || '';
  editPoolPaymentRequiredToScore.checked = Boolean(pool.paymentRequiredToScore);
  editPoolAllowOverrides.checked = Boolean(pool.allowPoolOverrides);
  editPoolEntryFee.value =
    pool.entryFeeCents === null || pool.entryFeeCents === undefined
      ? ''
      : (Number(pool.entryFeeCents) / 100).toFixed(2);
  toggleEditEntryFeeField();

  const locked = Boolean(pool.votingLocked);
  for (const control of poolSettingsForm.querySelectorAll('input, select, button')) {
    control.disabled = locked;
  }
  if (poolSettingsStatus) {
    if (locked) {
      poolSettingsStatus.textContent = 'Pool settings are locked while voting is locked.';
      poolSettingsStatus.classList.remove('error-note');
    } else if (!poolSettingsStatus.classList.contains('error-note')) {
      poolSettingsStatus.textContent = '';
    }
  }
};

const renderSubmissionStatus = () => {
  if (!state.session.loggedIn || !state.selectedPoolId) {
    submissionStatus.textContent = 'Select a pool to view submission status.';
    submitBallotButton.disabled = true;
    return;
  }
  const data = state.submissionStatus;
  if (!data) {
    submissionStatus.textContent = 'Loading submission status...';
    submitBallotButton.disabled = true;
    return;
  }
  const bits = [
    data.submitted ? `Submitted: ${data.submittedAt}` : 'Not submitted',
    `Progress: ${data.completeCount}/${data.totalCategories}`
  ];
  submissionStatus.textContent = bits.join(' | ');
  submitBallotButton.disabled = !data.canSubmit;
};

const renderLeaderboard = () => {
  leaderboardWrap.innerHTML = '';
  if (!state.selectedPoolId) {
    leaderboardWrap.textContent = 'Select a pool.';
    return;
  }
  if (!state.leaderboard.length) {
    leaderboardWrap.textContent = 'No leaderboard rows yet.';
    return;
  }
  const list = document.createElement('div');
  list.className = 'pool-leaderboard-list';
  for (const row of state.leaderboard) {
    const item = document.createElement('article');
    item.className = 'pool-leaderboard-card';
    const rank = row.rankPosition
      ? (row.tiedCount > 1 ? `T-${row.rankPosition}` : `#${row.rankPosition}`)
      : '—';
    item.innerHTML = `
      <h3>${row.displayName || row.userId}</h3>
      <p><strong>Rank:</strong> ${rank}</p>
      <p><strong>Points:</strong> ${row.totalPoints ?? '—'}</p>
      <p><strong>Correct:</strong> ${row.correctCount ?? '—'}</p>
      <p><strong>Eligible:</strong> ${row.eligible ? 'Yes' : 'No'}</p>
      <p><strong>Payment:</strong> ${row.paymentStatus || 'pending'}</p>
    `;
    list.append(item);
  }
  leaderboardWrap.append(list);
};

const renderTieReview = () => {
  if (!tieReviewWrap) {
    return;
  }
  tieReviewWrap.textContent = '';
  if (!state.selectedPoolId || !state.selectedPool) {
    return;
  }
  if (state.selectedPool.memberRole !== 'owner') {
    tieReviewWrap.textContent = 'Tie review is available to the pool owner.';
    return;
  }
  const top = state.leaderboard.find((row) => Number(row.rankPosition) === 1);
  if (!top || Number(top.tiedCount || 0) <= 1) {
    tieReviewWrap.textContent = 'No first-place tie right now.';
    return;
  }
  const names = state.leaderboard
    .filter((row) => Number(row.rankPosition) === 1)
    .map((row) => row.displayName || row.userId)
    .join(', ');
  tieReviewWrap.textContent = `Tie detected at #1 (${top.tiedCount} users): ${names}. Review tiebreaker answers and mark winner manually per your pool rules.`;
};

const renderMembers = () => {
  if (!membersWrap) {
    return;
  }
  membersWrap.innerHTML = '';
  if (!state.selectedPoolId) {
    membersWrap.textContent = 'Select a pool.';
    return;
  }
  if (!state.members.length) {
    membersWrap.textContent = 'No members found.';
    return;
  }
  const isOwner = state.selectedPool?.memberRole === 'owner';
  const list = document.createElement('div');
  list.className = 'pool-leaderboard-list';
  for (const member of state.members) {
    const card = document.createElement('article');
    card.className = 'pool-leaderboard-card';
    const editable = isOwner || member.userId === state.session.user?.id;
    card.innerHTML = `
      <h3>${member.displayName || member.userId}</h3>
      <p><strong>Role:</strong> ${member.role || 'member'}</p>
      <p><strong>Email:</strong> ${member.email || '—'}</p>
    `;
    const actions = document.createElement('div');
    actions.className = 'pool-invite-actions';
    if (editable) {
      const renameInput = document.createElement('input');
      renameInput.type = 'text';
      renameInput.value = member.displayName || '';
      renameInput.maxLength = 60;
      renameInput.dataset.action = 'member-rename-value';
      renameInput.dataset.userId = member.userId;
      const renameButton = document.createElement('button');
      renameButton.type = 'button';
      renameButton.dataset.action = 'member-rename';
      renameButton.dataset.userId = member.userId;
      renameButton.textContent = 'Save Name';
      actions.append(renameInput, renameButton);
    }
    if (isOwner && member.role !== 'owner') {
      const removeButton = document.createElement('button');
      removeButton.type = 'button';
      removeButton.className = 'danger';
      removeButton.dataset.action = 'member-remove';
      removeButton.dataset.userId = member.userId;
      removeButton.textContent = 'Remove';
      actions.append(removeButton);
    }
    card.append(actions);
    list.append(card);
  }
  membersWrap.append(list);
};

const renderResults = () => {
  resultsWrap.innerHTML = '';
  if (!state.selectedPoolId) {
    resultsWrap.textContent = 'Select a pool.';
    return;
  }
  if (!state.results.length) {
    resultsWrap.textContent = 'No results yet.';
    return;
  }
  for (const row of state.results) {
    const block = document.createElement('details');
    block.className = 'pools-result-block';
    const summary = document.createElement('summary');
    summary.textContent = `${row.userId} | payment: ${row.paymentStatus || 'pending'}`;
    block.append(summary);
    const body = document.createElement('div');
    body.className = 'pool-results-lines';
    for (const item of row.breakdown || []) {
      const line = document.createElement('p');
      line.className = `pool-result-line ${item.isCorrect ? 'ok' : 'miss'}`;
      line.textContent = `${item.category}: picked ${filmTitle(item.pickedFilmId)} | winner ${filmTitle(item.winnerFilmId)} | ${item.isCorrect ? 'correct' : 'incorrect'} | +${item.pointsAwarded ?? 0}`;
      body.append(line);
    }
    if (!(row.breakdown || []).length) {
      const empty = document.createElement('p');
      empty.className = 'small-note';
      empty.textContent = 'No scored picks yet.';
      body.append(empty);
    }
    block.append(body);
    resultsWrap.append(block);
  }
};

const inviteJoinUrl = (token) => `${window.location.origin}/join-pool.html?token=${encodeURIComponent(token)}`;

const renderInvites = () => {
  invitesWrap.innerHTML = '';
  const isOwner = state.selectedPool?.memberRole === 'owner';
  invitePermissionsNote.textContent = isOwner
    ? 'You can create, copy, and revoke invites.'
    : 'Only pool owners can manage invites.';
  inviteEmailForm.hidden = !isOwner;
  createShareLinkButton.hidden = !isOwner;

  if (!isOwner) {
    invitesWrap.textContent = 'Invite management hidden for non-owners.';
    return;
  }
  if (!state.invites.length) {
    invitesWrap.textContent = 'No invites yet.';
    return;
  }
  const list = document.createElement('div');
  list.className = 'pool-invite-list';
  for (const invite of state.invites) {
    const card = document.createElement('article');
    card.className = 'pool-invite-card';
    const joinUrl = invite.token ? inviteJoinUrl(invite.token) : '';
    card.innerHTML = `
      <h3>${invite.inviteType === 'share_link' ? 'Share Link' : 'Email Invite'}</h3>
      <p><strong>Email:</strong> ${invite.email || '—'}</p>
      <p><strong>Uses:</strong> ${invite.uses}/${invite.maxUses ?? '∞'}</p>
      <p><strong>Expires:</strong> ${invite.expiresAt || '—'}</p>
      ${joinUrl ? `<p class="invite-url">${joinUrl}</p>` : ''}
    `;
    const actions = document.createElement('div');
    actions.className = 'pool-invite-actions';
    if (joinUrl) {
      const copyButton = document.createElement('button');
      copyButton.type = 'button';
      copyButton.textContent = 'Copy Join Link';
      copyButton.addEventListener('click', async () => {
        try {
          await navigator.clipboard.writeText(joinUrl);
          showToast('Join link copied.');
        } catch {
          showToast('Clipboard unavailable. Copy manually.', 'error');
        }
      });
      actions.append(copyButton);
    }
    const revokeButton = document.createElement('button');
    revokeButton.type = 'button';
    revokeButton.className = 'danger';
    revokeButton.textContent = 'Revoke';
    revokeButton.addEventListener('click', async () => {
      try {
        await api(`/api/pools/${encodeURIComponent(state.selectedPoolId)}/invites/${encodeURIComponent(invite.id)}/revoke`, {
          method: 'POST'
        });
        showToast('Invite revoked.');
        await refreshAll();
      } catch (error) {
        showToast(`Revoke failed: ${error.message}`, 'error');
      }
    });
    actions.append(revokeButton);
    card.append(actions);
    list.append(card);
  }
  invitesWrap.append(list);
};

const render = () => {
  renderAuth();
  renderYears();
  renderPools();
  renderPoolMeta();
  renderPoolSettingsEditor();
  renderGlobalPicks();
  renderPoolPicks();
  renderSubmissionStatus();
  renderLeaderboard();
  renderTieReview();
  renderMembers();
  renderResults();
  renderInvites();
};

const refreshAll = async () => {
  try {
    await loadSession();
    await loadYears();
    await loadNominees();
    await loadPools();
    await loadGlobalPicks();
    await loadPoolData();
    render();
    setMessage('');
  } catch (error) {
    render();
    setMessage(`Failed to load pools page: ${error.message}`, true);
    showToast(`Load failed: ${error.message}`, 'error');
  }
};

loginForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  try {
    await api('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: document.getElementById('loginEmail').value.trim(),
        password: document.getElementById('loginPassword').value
      })
    });
    await refreshAll();
    showToast('Signed in.');
  } catch (error) {
    setMessage(`Sign in failed: ${error.message}`, true);
    showToast(`Sign in failed: ${error.message}`, 'error');
  }
});

registerForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  try {
    await api('/api/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: document.getElementById('registerEmail').value.trim(),
        displayName: document.getElementById('registerDisplayName').value.trim(),
        password: document.getElementById('registerPassword').value
      })
    });
    await refreshAll();
    showToast('Account created.');
  } catch (error) {
    setMessage(`Registration failed: ${error.message}`, true);
    showToast(`Registration failed: ${error.message}`, 'error');
  }
});

logoutButton.addEventListener('click', async () => {
  try {
    await api('/api/auth/logout', { method: 'POST' });
    await refreshAll();
    showToast('Logged out.');
  } catch (error) {
    setMessage(`Logout failed: ${error.message}`, true);
    showToast(`Logout failed: ${error.message}`, 'error');
  }
});

yearSelect.addEventListener('change', async () => {
  state.year = Number(yearSelect.value);
  await refreshAll();
});

poolSelect.addEventListener('change', async () => {
  state.selectedPoolId = poolSelect.value;
  await refreshAll();
});

refreshPoolsButton.addEventListener('click', refreshAll);

createPoolForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  try {
    let entryFeeCents = null;
    if (newPoolEntryMode.value === 'manual_transfer') {
      const feeRaw = String(newPoolEntryFee.value || '').trim();
      if (feeRaw) {
        const fee = Number(feeRaw);
        if (!Number.isFinite(fee) || fee < 0) {
          throw new Error('Entry fee must be a valid non-negative amount.');
        }
        entryFeeCents = Math.round(fee * 100);
      } else {
        entryFeeCents = 0;
      }
    }
    const payload = await api('/api/pools', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: document.getElementById('newPoolName').value.trim(),
        ownerDisplayName: document.getElementById('ownerDisplayName').value.trim(),
        description: (newPoolDescription.value || '').trim(),
        scoringMode: newPoolScoringMode.value,
        entryMode: newPoolEntryMode.value,
        entryFeeCents,
        currency: 'USD',
        paymentRequiredToScore: Boolean(newPoolPaymentRequiredToScore.checked),
        allowPoolOverrides: Boolean(newPoolAllowOverrides.checked),
        invitePolicy: newPoolInvitePolicy.value,
        tiebreakerQuestion: (newPoolTiebreakerQuestion.value || '').trim()
      })
    });
    createPoolForm.reset();
    newPoolScoringMode.value = 'standard';
    newPoolEntryMode.value = 'none';
    newPoolInvitePolicy.value = 'both';
    newPoolPaymentRequiredToScore.checked = true;
    newPoolAllowOverrides.checked = true;
    toggleEntryFeeField();
    state.selectedPoolId = payload.pool.id;
    await refreshAll();
    showToast('Pool created.');
  } catch (error) {
    setMessage(`Failed to create pool: ${error.message}`, true);
    showToast(`Create pool failed: ${error.message}`, 'error');
  }
});

newPoolEntryMode.addEventListener('change', toggleEntryFeeField);

editPoolEntryMode.addEventListener('change', toggleEditEntryFeeField);

poolSettingsForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!state.selectedPoolId || state.selectedPool?.memberRole !== 'owner') {
    return;
  }
  try {
    let entryFeeCents = null;
    if (editPoolEntryMode.value === 'manual_transfer') {
      const feeRaw = String(editPoolEntryFee.value || '').trim();
      if (feeRaw) {
        const fee = Number(feeRaw);
        if (!Number.isFinite(fee) || fee < 0) {
          throw new Error('Entry fee must be a valid non-negative amount.');
        }
        entryFeeCents = Math.round(fee * 100);
      } else {
        entryFeeCents = 0;
      }
    }
    await api(`/api/pools/${encodeURIComponent(state.selectedPoolId)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: editPoolName.value.trim(),
        description: (editPoolDescription.value || '').trim(),
        scoringMode: editPoolScoringMode.value,
        entryMode: editPoolEntryMode.value,
        entryFeeCents,
        currency: 'USD',
        paymentRequiredToScore: Boolean(editPoolPaymentRequiredToScore.checked),
        allowPoolOverrides: Boolean(editPoolAllowOverrides.checked),
        invitePolicy: editPoolInvitePolicy.value,
        tiebreakerQuestion: (editPoolTiebreakerQuestion.value || '').trim()
      })
    });
    poolSettingsStatus.textContent = 'Pool settings saved.';
    poolSettingsStatus.classList.remove('error-note');
    await refreshAll();
    showToast('Pool settings saved.');
  } catch (error) {
    poolSettingsStatus.textContent = `Save failed: ${error.message}`;
    poolSettingsStatus.classList.add('error-note');
    showToast(`Save failed: ${error.message}`, 'error');
  }
});

submitBallotForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!state.selectedPoolId) {
    return;
  }
  try {
    await api(`/api/pools/${encodeURIComponent(state.selectedPoolId)}/submit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tiebreakerAnswer: (tiebreakerAnswer.value || '').trim()
      })
    });
    await refreshAll();
    showToast('Pool ballot submitted.');
  } catch (error) {
    setMessage(`Submission failed: ${error.message}`, true);
    showToast(`Submit failed: ${error.message}`, 'error');
  }
});

inviteEmailForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!state.selectedPoolId) {
    showToast('Select a pool first.', 'error');
    return;
  }
  try {
    await api(`/api/pools/${encodeURIComponent(state.selectedPoolId)}/invites/email`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: inviteEmailInput.value.trim() })
    });
    inviteEmailInput.value = '';
    await refreshAll();
    showToast('Email invite created.');
  } catch (error) {
    setMessage(`Invite failed: ${error.message}`, true);
    showToast(`Invite failed: ${error.message}`, 'error');
  }
});

createShareLinkButton.addEventListener('click', async () => {
  if (!state.selectedPoolId) {
    showToast('Select a pool first.', 'error');
    return;
  }
  try {
    await api(`/api/pools/${encodeURIComponent(state.selectedPoolId)}/invites/link`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({})
    });
    await refreshAll();
    showToast('Share-link invite created.');
  } catch (error) {
    setMessage(`Share link failed: ${error.message}`, true);
    showToast(`Share link failed: ${error.message}`, 'error');
  }
});

membersWrap.addEventListener('click', async (event) => {
  const renameButton = event.target.closest('[data-action="member-rename"]');
  if (renameButton) {
    const userId = renameButton.dataset.userId;
    const input = membersWrap.querySelector(
      `input[data-action="member-rename-value"][data-user-id="${userId}"]`
    );
    if (!(input instanceof HTMLInputElement)) {
      return;
    }
    const displayName = input.value.trim();
    if (!displayName) {
      showToast('Display name is required.', 'error');
      return;
    }
    try {
      await api(
        `/api/pools/${encodeURIComponent(state.selectedPoolId)}/members/${encodeURIComponent(userId)}/display-name`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ displayName })
        }
      );
      await refreshAll();
      showToast('Display name updated.');
    } catch (error) {
      showToast(`Rename failed: ${error.message}`, 'error');
    }
    return;
  }

  const removeButton = event.target.closest('[data-action="member-remove"]');
  if (removeButton) {
    const userId = removeButton.dataset.userId;
    const ok = window.confirm('Remove this member from the pool?');
    if (!ok) {
      return;
    }
    try {
      await api(
        `/api/pools/${encodeURIComponent(state.selectedPoolId)}/members/${encodeURIComponent(userId)}`,
        { method: 'DELETE' }
      );
      await refreshAll();
      showToast('Member removed.');
    } catch (error) {
      showToast(`Remove failed: ${error.message}`, 'error');
    }
  }
});

refreshAll();
toggleEntryFeeField();
toggleEditEntryFeeField();
