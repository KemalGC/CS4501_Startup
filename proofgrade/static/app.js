const form = document.querySelector('#practice-form');
const problemSelect = document.querySelector('#problem');
const stepsElement = document.querySelector('#steps');
const feedbackElement = document.querySelector('#feedback');
const checkButton = document.querySelector('#check');
const exampleButton = document.querySelector('#example');
let problems = [];
let busy = false;
let lastAttemptId = null;
let collectionEnabled = false;
const initialFeedback = feedbackElement.cloneNode(true);

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function clearFeedback() {
  feedbackElement.replaceChildren(...Array.from(initialFeedback.childNodes, node => node.cloneNode(true)));
  stepsElement.querySelectorAll('.step-row').forEach(row => {
    row.classList.remove('error');
    row.querySelector('input').removeAttribute('aria-invalid');
  });
}

function numberRows() {
  const rows = stepsElement.querySelectorAll('.step-row');
  rows.forEach((row, index) => {
    const id = `step-${index + 1}`;
    row.querySelector('label').textContent = `Step ${index + 1}`;
    row.querySelector('label').htmlFor = id;
    row.querySelector('input').id = id;
    row.querySelector('button').setAttribute('aria-label', `Remove step ${index + 1}`);
    row.querySelector('button').disabled = busy || rows.length === 1;
  });
  document.querySelector('#add-step').disabled = busy || rows.length >= 20;
}

function addStep(value = '') {
  if (stepsElement.children.length >= 20) return;
  const row = element('div', undefined, 'step-row');
  const label = element('label');
  const input = element('input');
  input.type = 'text';
  input.value = value;
  input.required = true;
  input.maxLength = 256;
  input.autocomplete = 'off';
  input.spellcheck = false;
  input.setAttribute('aria-describedby', 'notation');
  input.addEventListener('input', clearFeedback);
  const remove = element('button', '×', 'remove-step');
  remove.type = 'button';
  remove.addEventListener('click', () => {
    if (busy || stepsElement.children.length === 1) return;
    row.remove();
    numberRows();
    clearFeedback();
  });
  row.append(label, input, remove);
  stepsElement.append(row);
  numberRows();
}

function selectProblem() {
  lastAttemptId = null;
  const selected = problems.find(problem => problem.id === problemSelect.value);
  document.querySelector('#equation').textContent = selected.equation;
  stepsElement.replaceChildren();
  addStep();
  exampleButton.hidden = selected.id !== 'linear-distribution';
  clearFeedback();
}

function setBusy(value) {
  busy = value;
  form.querySelectorAll('input,select,button').forEach(control => { control.disabled = value; });
  checkButton.textContent = value ? 'Checking your steps…' : 'Check my work ↗';
  form.setAttribute('aria-busy', String(value));
  numberRows();
}

function showResult(result) {
  const titles = {
    correct: 'You’ve got it.', incomplete: 'You’re on the right track.',
    incorrect: `Take another look at step ${result.first_error_step}.`,
    unsupported: 'Let’s check the notation.'
  };
  feedbackElement.replaceChildren(
    element('span', result.status === 'correct' ? 'COMPLETE' : result.status.toUpperCase(), `result-tag ${result.status}`),
    element('h3', titles[result.status]), element('p', result.message)
  );
  const index = result.first_error_step || result.unsupported_step;
  if (index) {
    const row = stepsElement.children[index - 1];
    if (row) {
      row.classList.add('error');
      row.querySelector('input').setAttribute('aria-invalid', 'true');
    }
  }
  if (result.hint_status === 'verified' && result.hint) {
    const box = element('div', undefined, 'hint-box');
    box.append(element('span', 'One checked hint', 'eyebrow'), element('p', result.hint));
    feedbackElement.append(box, element('p', 'Revise your steps and check again.', 'quiet'));
    if (result.attempt_id) addRating(result.attempt_id);
  } else if (['manual_review', 'unavailable'].includes(result.hint_status)) {
    feedbackElement.append(element('p', 'This solution needs manual review. No verified hint is available; ask a tutor to review the highlighted step.'));
  }
}

function addRating(attemptId) {
  const panel = element('div', undefined, 'rating-panel');
  const label = element('label', 'How helpful was this hint?');
  label.htmlFor = 'hint-rating';
  const select = element('select');
  select.id = 'hint-rating';
  const placeholder = element('option', 'Choose a rating (optional)');
  placeholder.value = '';
  select.append(placeholder);
  for (let rating = 1; rating <= 5; rating += 1) {
    const option = element('option', `${rating} / 5${rating === 1 ? ' · not helpful' : rating === 5 ? ' · very helpful' : ''}`);
    option.value = String(rating);
    select.append(option);
  }
  const button = element('button', 'Save rating', 'text-button');
  button.type = 'button';
  button.addEventListener('click', async () => {
    if (!select.value) return;
    button.disabled = true;
    try {
      const response = await fetch(`/api/attempts/${encodeURIComponent(attemptId)}/rating`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({rating: Number(select.value)})
      });
      if (!response.ok) throw new Error('Rating could not be saved. Try again.');
      panel.replaceChildren(element('p', 'Thanks—your rating has been saved.', 'help'));
    } catch (error) {
      button.disabled = false;
      button.textContent = error.message;
    }
  });
  panel.append(label, select, button);
  feedbackElement.append(panel);
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  if (busy || !form.reportValidity()) return;
  const payload = {problem_id: problemSelect.value,
    steps: Array.from(stepsElement.querySelectorAll('input'), input => input.value.trim()),
    consent: collectionEnabled && document.querySelector('#consent').checked,
    previous_attempt_id: lastAttemptId};
  clearFeedback();
  setBusy(true);
  try {
    const response = await fetch('/api/check', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
    if (!response.ok) throw new Error('We couldn’t check these steps. Check that each line contains an equation, then try again.');
    const result = await response.json();
    lastAttemptId = result.attempt_id;
    showResult(result);
  } catch (error) {
    feedbackElement.replaceChildren(element('h3', 'Something interrupted the check.'), element('p', error.message));
  } finally {
    setBusy(false);
  }
});

problemSelect.addEventListener('change', selectProblem);
document.querySelector('#consent').addEventListener('change', () => {
  lastAttemptId = null;
  clearFeedback();
});
document.querySelector('#add-step').addEventListener('click', () => {
  addStep();
  clearFeedback();
  stepsElement.lastElementChild.querySelector('input').focus();
});
document.querySelector('#reset').addEventListener('click', selectProblem);
exampleButton.addEventListener('click', () => {
  lastAttemptId = null;
  stepsElement.replaceChildren();
  ['2x+3=10', '2x=7'].forEach(addStep);
  clearFeedback();
});

async function start() {
  try {
    const [problemResponse, configResponse] = await Promise.all([fetch('/api/problems'), fetch('/api/config')]);
    if (!problemResponse.ok || !configResponse.ok) throw new Error('Could not load practice problems. Refresh to try again.');
    problems = await problemResponse.json();
    const config = await configResponse.json();
    collectionEnabled = config.collection_enabled;
    document.querySelector('#consent-panel').hidden = !collectionEnabled;
    document.querySelector('#model-notice').hidden = config.provider_mode !== 'openai';
    const modeLabels = {demo: 'Local demo · no AI calls', openai: 'AI hints · checked before display', disabled: 'Algebra checks · hints off'};
    document.querySelector('#mode').textContent = modeLabels[config.provider_mode] || 'Practice mode';
    problemSelect.replaceChildren(...problems.map(problem => {
      const option = element('option', `${problem.topic} · ${problem.title}`);
      option.value = problem.id;
      return option;
    }));
    selectProblem();
    setBusy(false);
  } catch (error) {
    document.querySelector('#mode').textContent = 'Connection unavailable';
    feedbackElement.replaceChildren(element('h3', 'Practice is unavailable.'), element('p', error.message));
  }
}
start();
