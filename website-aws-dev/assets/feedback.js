(function () {
  'use strict';

  const form = document.getElementById('feedback-form');
  const status = document.getElementById('feedback-status');
  const submit = document.getElementById('feedback-submit');
  if (!form || !status || !submit) return;

  const apiBase = String((window.STROKESENSE_AWS_CONFIG || {}).apiBaseUrl || '').replace(/\/+$/, '');
  let sending = false;

  function setStatus(message, tone = '') {
    status.textContent = message;
    status.dataset.tone = tone;
  }

  if (!/^https:\/\/[^/]+/.test(apiBase)) {
    submit.disabled = true;
    setStatus('Feedback is temporarily unavailable. Please try again later.', 'error');
    return;
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (sending) return;

    const selected = form.querySelector('input[name="rating"]:checked');
    const rating = Number(selected && selected.value);
    if (!Number.isInteger(rating) || rating < 1 || rating > 5) {
      setStatus('Choose a usability rating from 1 to 5.', 'error');
      return;
    }

    const comment = form.elements.comment.value.trim();
    if (comment.length > 1000) {
      setStatus('Keep your comment under 1,000 characters.', 'error');
      return;
    }

    sending = true;
    submit.disabled = true;
    setStatus('Sending your feedback…');
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 15000);

    try {
      const response = await fetch(apiBase + '/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'omit',
        cache: 'no-store',
        body: JSON.stringify({ rating, comment }),
        signal: controller.signal
      });
      if (!response.ok) {
        if (response.status === 429) throw new Error('Too many feedback submissions right now. Please try again tomorrow.');
        throw new Error('Your feedback could not be submitted. Please try again later.');
      }
      form.reset();
      setStatus('Thank you! Your feedback has been sent.', 'success');
    } catch (error) {
      const message = error && error.name === 'AbortError'
        ? 'The request timed out. Please check your connection and try again.'
        : (error && error.message && error.message.startsWith('Too many feedback')
            ? error.message
            : 'Your feedback could not be submitted. Please check your connection and try again.');
      setStatus(message, 'error');
    } finally {
      window.clearTimeout(timeout);
      sending = false;
      submit.disabled = false;
    }
  });
})();
