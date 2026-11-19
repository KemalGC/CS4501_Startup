import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { runInNewContext } from 'node:vm';

const page = readFileSync(new URL('../feedback/index.html', import.meta.url), 'utf8');
const main = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const analyzer = readFileSync(new URL('../demos/index.html', import.meta.url), 'utf8');
const oldStudy = readFileSync(new URL('../study/index.html', import.meta.url), 'utf8');
const client = readFileSync(new URL('../assets/feedback.js', import.meta.url), 'utf8');

function harness({ api = 'https://example.execute-api.us-east-1.amazonaws.com', rating = '4', comment = 'Clear reports', responseStatus = 201 } = {}) {
  const requests = [];
  let onSubmit;
  const status = { textContent: '', dataset: {} };
  const submit = { disabled: false };
  const form = {
    elements: { comment: { value: comment } },
    addEventListener(event, handler) { if (event === 'submit') onSubmit = handler; },
    querySelector(selector) { return selector === 'input[name="rating"]:checked' && rating ? { value: rating } : null; },
    reset() { this.elements.comment.value = ''; }
  };
  const elements = { 'feedback-form': form, 'feedback-status': status, 'feedback-submit': submit };
  runInNewContext(client, {
    document: { getElementById(id) { return elements[id]; } },
    window: {
      STROKESENSE_AWS_CONFIG: { apiBaseUrl: api },
      setTimeout() { return 1; },
      clearTimeout() {}
    },
    AbortController,
    fetch: async (url, options) => {
      requests.push({ url, options });
      return { ok: responseStatus >= 200 && responseStatus < 300, status: responseStatus };
    }
  });
  return {
    requests, status, submit,
    async submitForm() {
      assert.equal(typeof onSubmit, 'function');
      await onSubmit({ preventDefault() {} });
    }
  };
}

test('website pages link to usable feedback instead of the private study', () => {
  assert.match(page, /<title>Website Feedback/);
  assert.match(page, /id="feedback-form"/);
  assert.match(page, /name="comment"[^>]*maxlength="1000"/);
  const ratings = [...page.matchAll(/type="radio" name="rating" value="(\d)" required/g)].map((match) => Number(match[1]));
  assert.deepEqual(ratings, [1, 2, 3, 4, 5]);
  assert.match(main, /href="\/feedback\/">Feedback/);
  assert.match(analyzer, /href="\/feedback\/">Feedback/);
  assert.doesNotMatch(main + analyzer + page, /Feedback study|feedback study|Open feedback study/);
  assert.match(oldStudy, /http-equiv="refresh" content="0; url=\/feedback\/"/);
});

test('feedback form sends rating and optional comment to public API', async () => {
  const app = harness({ rating: '4', comment: '   Great interface   ' });
  await app.submitForm();
  assert.equal(app.requests.length, 1);
  assert.equal(app.requests[0].url, 'https://example.execute-api.us-east-1.amazonaws.com/feedback');
  assert.equal(app.requests[0].options.method, 'POST');
  assert.equal(app.requests[0].options.credentials, 'omit');
  assert.deepEqual(JSON.parse(app.requests[0].options.body), { rating: 4, comment: 'Great interface' });
  assert.match(app.status.textContent, /Thank you/);
  assert.equal(app.status.dataset.tone, 'success');
  assert.equal(app.submit.disabled, false);
});

test('unconfigured API and invalid usability scores never submit feedback', async () => {
  const disconnected = harness({ api: '' });
  assert.equal(disconnected.submit.disabled, true);
  assert.match(disconnected.status.textContent, /temporarily unavailable/);

  const invalid = harness({ rating: '' });
  await invalid.submitForm();
  assert.equal(invalid.requests.length, 0);
  assert.match(invalid.status.textContent, /Choose a usability rating/);
});

test('submission rate limit is shown without clearing the comment', async () => {
  const blocked = harness({ responseStatus: 429, comment: 'The form is confusing' });
  await blocked.submitForm();
  assert.equal(blocked.status.dataset.tone, 'error');
  assert.match(blocked.status.textContent, /try again tomorrow/);
  assert.equal(blocked.submit.disabled, false);
});
