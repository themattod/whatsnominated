const loginForm = document.getElementById('adminLoginForm');
const forgotPasswordButton = document.getElementById('forgotPasswordButton');
const emailInput = document.getElementById('email');
const passwordInput = document.getElementById('password');
const loginStatus = document.getElementById('loginStatus');

const setStatus = (message, isError = false) => {
  loginStatus.textContent = message;
  loginStatus.classList.toggle('error', Boolean(isError));
};

const api = async (path, options = {}) => {
  const response = await fetch(path, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || `API error ${response.status}`);
  }
  return payload;
};

const init = async () => {
  try {
    const session = await api('/api/admin-auth/session');
    if (session.loggedIn) {
      window.location.href = '/admin.html';
    }
  } catch {
    // no-op
  }
};

loginForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  setStatus('Signing in...');
  try {
    await api('/api/admin-auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: emailInput.value.trim(),
        password: passwordInput.value
      })
    });
    window.location.href = '/admin.html';
  } catch (error) {
    setStatus(error.message, true);
  }
});

forgotPasswordButton.addEventListener('click', async () => {
  const email = emailInput.value.trim();
  if (!email) {
    setStatus('Enter your admin email first, then click Reset Password.', true);
    return;
  }
  setStatus('Sending reset email...');
  try {
    await api('/api/admin-auth/request-reset', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email })
    });
    setStatus('If the account exists, a reset email has been sent.');
  } catch (error) {
    setStatus(error.message, true);
  }
});

init();
