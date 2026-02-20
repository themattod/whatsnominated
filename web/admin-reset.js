const form = document.getElementById('adminResetForm');
const newPasswordInput = document.getElementById('newPassword');
const confirmPasswordInput = document.getElementById('confirmPassword');
const resetStatus = document.getElementById('resetStatus');

const setStatus = (message, isError = false) => {
  resetStatus.textContent = message;
  resetStatus.classList.toggle('error', Boolean(isError));
};

const api = async (path, options = {}) => {
  const response = await fetch(path, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || `API error ${response.status}`);
  }
  return payload;
};

const params = new URLSearchParams(window.location.search);
const token = (params.get('token') || '').trim();

if (!token) {
  setStatus('Missing reset token. Open the reset link from your email.', true);
  form.querySelector('button[type="submit"]').disabled = true;
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const password = newPasswordInput.value;
  const confirm = confirmPasswordInput.value;

  if (password !== confirm) {
    setStatus('Passwords do not match.', true);
    return;
  }

  setStatus('Saving...');
  try {
    await api('/api/admin-auth/reset', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token, password })
    });
    setStatus('Password updated. Redirecting to admin...');
    setTimeout(() => {
      window.location.href = '/admin.html';
    }, 800);
  } catch (error) {
    setStatus(error.message, true);
  }
});
