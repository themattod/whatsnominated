const form = document.getElementById('contactForm');
const nameInput = document.getElementById('contactName');
const emailInput = document.getElementById('contactEmail');
const topicInput = document.getElementById('contactTopic');
const messageInput = document.getElementById('contactMessage');
const statusEl = document.getElementById('contactStatus');

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

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  statusEl.textContent = 'Sending...';
  statusEl.classList.remove('error');

  try {
    const payload = await api('/api/contact', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: nameInput.value.trim(),
        email: emailInput.value.trim(),
        topic: topicInput.value.trim(),
        message: messageInput.value.trim()
      })
    });

    if (payload.sent === false) {
      statusEl.textContent = 'Thanks. Message received; delivery will retry shortly.';
    } else {
      statusEl.textContent = 'Thanks. Message sent.';
    }
    form.reset();
  } catch (error) {
    statusEl.textContent = `Unable to send message. ${error.message}`;
    statusEl.classList.add('error');
  }
});
