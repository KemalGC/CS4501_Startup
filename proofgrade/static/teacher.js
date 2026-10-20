'use strict';

const app = document.querySelector('#app');
const notice = document.querySelector('#notice');
const state = {session: null, assignments: [], assignment: null, submission: null};
const apiRoot = '/api/teacher';
const statuses = {transcription_draft: 'Review transcription', grading_draft: 'Review grades', approved: 'Approved'};

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else if (key === 'class') node.className = value;
    else if (key in node && key !== 'list') node[key] = value;
    else node.setAttribute(key, value);
  }
  for (const child of children.flat(Infinity)) {
    if (child !== null && child !== undefined) node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}
function message(text = '', error = false) { notice.textContent = text; notice.className = error ? 'error' : ''; }
async function api(path, method = 'GET', body) {
  const response = await fetch(apiRoot + path, {
    method, credentials: 'same-origin',
    headers: {'X-ProofGrade-Request': '1', ...(body !== undefined ? {'Content-Type': 'application/json'} : {})},
    ...(body !== undefined ? {body: JSON.stringify(body)} : {})
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const detail = Array.isArray(data.detail) ? data.detail.map(x => x.loc.join('.') + ': ' + x.msg).join('; ') : data.detail;
    if (response.status === 401 && path !== '/login') { state.session = null; loginView(); }
    throw new Error(detail || 'The request could not be completed.');
  }
  return response.json();
}
async function run(action, pending = '') {
  if (app.getAttribute('aria-busy') === 'true') return;
  app.setAttribute('aria-busy', 'true');
  app.inert = true;
  message(pending);
  try { await action(); }
  catch (error) { message(error.message, true); }
  finally { app.inert = false; app.setAttribute('aria-busy', 'false'); }
}
function button(text, action, style = '') { return el('button', {type: 'button', class: style, onclick: () => run(action)}, text); }
function link(text, path, style = 'secondary') { return el('a', {class: 'button-link ' + style, href: apiRoot + path}, text); }
function badge(status) { return el('span', {class: 'badge ' + status}, statuses[status] || status); }
function label(text, control) { return el('label', {}, text, control); }
function input(id, value = '', attrs = {}) { return el('input', {id, name: id, value, ...attrs}); }
function select(id, values, selected) {
  return el('select', {id, name: id}, values.map(([value, text]) => el('option', {value, selected: value === selected}, text)));
}
function table(headers, rows) {
  return el('div', {class: 'table-wrap'}, el('table', {},
    el('thead', {}, el('tr', {}, headers.map(h => el('th', {scope: 'col'}, h)))),
    el('tbody', {}, rows.map(cells => el('tr', {}, cells.map(c => el('td', {}, c)))))));
}
function empty(title, text) { return el('div', {class: 'empty'}, el('div', {class: 'empty-icon'}, '∑'), el('h2', {}, title), el('p', {}, text)); }
function setAccount() {
  document.querySelector('#account').textContent = state.session?.username || '';
  document.querySelector('#logout').hidden = !state.session?.authenticated;
}
document.querySelector('#logout').addEventListener('click', () => run(async () => {
  await api('/logout', 'POST'); state.session = null; state.assignments = []; loginView(); message('Signed out.');
}));

function loginView() {
  setAccount();
  const username = input('username', '', {required: true, autocomplete: 'username', minLength: 3, maxLength: 64});
  const password = input('password', '', {required: true, type: 'password', autocomplete: 'current-password', maxLength: 128});
  const form = el('form', {class: 'card', onsubmit: event => {
    event.preventDefault();
    run(async () => {
      await api('/login', 'POST', {username: username.value, password: password.value});
      state.session = await api('/session'); setAccount(); await home(); message();
    }, 'Signing in…');
  }}, el('div', {class: 'eyebrow'}, 'YOUR PRIVATE WORKSPACE'), el('h2', {}, 'Welcome back'),
  label('Username', username), label('Password', password), el('button', {type: 'submit'}, 'Sign in'),
  el('p', {class: 'footnote'}, 'Use the teacher account created by your administrator. Uploaded work is visible only in your workspace.'));
  app.replaceChildren(el('section', {class: 'login'},
    el('div', {}, el('div', {class: 'eyebrow'}, 'LESS SORTING. MORE UNDERSTANDING.'),
      el('h1', {}, 'See the work.', el('br'), 'Know what comes next.'),
      el('p', {class: 'muted'}, 'Bring handwritten algebra homework into one place. Review the transcription and suggested grades, spot shared difficulties, and prepare focused practice.'),
      el('ul', {}, el('li', {}, 'Review every suggested score before release'), el('li', {}, 'Keep source work beside the feedback'), el('li', {}, 'Turn confirmed gaps into the next lesson'))),
    form));
}

async function home(id) {
  state.assignments = await api('/assignments');
  state.assignment = id ? state.assignments.find(a => a.id === id) : state.assignments[0] || null;
  state.submission = null;
  await dashboard();
}
function frame(content) {
  const sidebar = el('aside', {class: 'sidebar'},
    button('+ New assignment', async () => assignmentForm(), 'new-button'),
    el('div', {class: 'section-label'}, 'YOUR ASSIGNMENTS'),
    el('div', {class: 'assignment-list'}, state.assignments.map(a => el('button', {
      type: 'button', class: 'assignment-item' + (state.assignment?.id === a.id ? ' active' : ''),
      onclick: () => run(() => home(a.id))
    }, a.title, el('small', {}, a.class_name)))),
    el('p', {class: 'sidebar-note'}, state.session.vision_mode === 'openai'
      ? 'AI transcription is available. Uploaded pages are sent to the configured model only when you request extraction. Always review the draft.'
      : 'Manual transcription mode. Image and PDF uploads work; enter the equations beside each source page. AI extraction requires server configuration.'));
  app.replaceChildren(el('div', {class: 'layout'}, sidebar, el('section', {}, content)));
}

async function dashboard() {
  const a = state.assignment;
  if (!a) {
    frame(el('div', {},
      el('div', {class: 'eyebrow'}, 'YOUR CLASS, AT A GLANCE'),
      el('h1', {}, 'A fresh start for grading.'),
      el('p', {class: 'muted'}, 'Set up a short algebra assignment with its answer key and rubric, then add student work.'),
      el('div', {class: 'card'}, empty('Your first assignment starts here', 'Use up to five linear or quadratic questions. You stay in control of the final grades.'),
        el('div', {class: 'toolbar'}, button('Create an assignment', async () => assignmentForm()),
          button('Try a synthetic demo', createDemo, 'secondary')),
        el('p', {class: 'footnote'}, 'The demo contains typed developer examples, not real student work or handwriting recognition results.'))));
    return;
  }
  const [submissions, summary, practice] = await Promise.all([
    api('/assignments/' + a.id + '/submissions'), api('/assignments/' + a.id + '/analytics'),
    api('/assignments/' + a.id + '/practice')
  ]);
  const average = summary.students.length ? Math.round(summary.students.reduce((sum, s) => sum + s.percent, 0) / summary.students.length) + '%' : '—';
  const metrics = [['Submitted', summary.submitted, 'Student responses'], ['Approved', summary.approved, 'Included in summaries'],
    ['Awaiting review', summary.unresolved, 'Transcription or grading'], ['Average score', average, 'Approved responses only']];
  const top = el('div', {class: 'heading-row'}, el('div', {}, el('div', {class: 'eyebrow'}, a.class_name), el('h1', {}, a.title),
    el('p', {class: 'muted'}, a.questions.length + ' questions · ' + a.questions.reduce((s, q) => s + q.criteria.reduce((t, c) => t + c.points, 0), 0) + ' points · Algebra')),
    el('div', {class: 'toolbar'}, link('Export grades', '/assignments/' + a.id + '/grades.csv')));
  const statCards = el('div', {class: 'stats'}, metrics.map(([name, value, note]) => el('div', {class: 'stat'},
    el('div', {class: 'stat-label'}, name), el('div', {class: 'stat-value'}, value), el('div', {class: 'stat-note'}, note))));
  const queue = el('div', {class: 'card'}, el('div', {class: 'heading-row'}, el('div', {}, el('h2', {}, 'Student work'),
    el('p', {class: 'muted'}, 'Review the source first, then approve the scores.')), badge(summary.unresolved + ' pending')));
  if (!submissions.length) queue.append(empty('No submissions yet', 'Upload photos or scanned worksheets below, or add a typed response.'));
  else queue.append(table(['Student', 'Progress', 'Score', ''], submissions.map(s => [
    s.student_code, badge(s.status),
    s.status === 'approved' ? s.results.reduce((sum, r) => sum + r.earned, 0) + '/' + s.results.reduce((sum, r) => sum + r.possible, 0) : '—',
    button('Review ' + s.student_code, () => openSubmission(s.id), 'secondary')
  ])));
  const gapCard = el('div', {class: 'card'}, el('h2', {}, 'Where to focus next'),
    el('p', {class: 'muted'}, 'Skills with lost points in teacher-approved results.'));
  if (!summary.gaps.length) gapCard.append(el('p', {class: 'footnote'}, 'Approve student work to see skill gaps. No unreviewed scores are counted.'));
  for (const gap of summary.gaps) gapCard.append(el('div', {class: 'gap-row'},
    el('div', {}, el('strong', {}, gap.skill), el('small', {}, gap.responses + ' reviewed question responses need practice')),
    button('Create practice', async () => {
      message('Preparing and checking a practice set…');
      await api('/assignments/' + a.id + '/practice', 'POST', {skill: gap.skill});
      await dashboard(); message('Practice draft created. Review its answer keys before sharing.');
    }, 'secondary')));
  const questions = el('div', {class: 'card'}, el('h2', {}, 'Question breakdown'),
    table(['Question', 'Skill', 'Full credit', 'Average'], summary.questions.map(q => [
      q.question_id, q.skill, q.full_credit + '/' + q.reviewed, q.mean_percent === null ? '—' : q.mean_percent + '%'
    ])), el('p', {class: 'footnote'}, 'Results describe this assignment, not mastery of an entire topic.'));
  const progress = el('div', {class: 'card'}, el('h2', {}, 'Student progress'));
  if (!summary.students.length) progress.append(el('p', {class: 'muted'}, 'Progress appears after approval.'));
  for (const student of summary.students) {
    const history = el('div', {});
    progress.append(el('div', {class: 'gap-row'}, el('span', {}, student.student_code + ' · ' + student.percent + '%'),
      button('View history', async () => {
        const rows = await api('/students/' + encodeURIComponent(student.student_code) + '/progress?class_name=' + encodeURIComponent(a.class_name));
        history.replaceChildren(...rows.map(r => el('div', {class: 'progress-entry'}, r.assignment + ': ' + r.earned + '/' + r.possible + ' (' + r.percent + '%)')));
      }, 'quiet')), history);
  }
  const keys = el('details', {}, el('summary', {}, 'Assignment answer keys and rubric'),
    table(['Question', 'Equation', 'Answer key', 'Rubric'], a.questions.map(q => [
      q.id, q.equation, q.answer, q.criteria.map(c => c.label + ': ' + c.points).join(' · ')
    ])));
  frame([top, statCards, queue, uploadCard(a), el('div', {class: 'two-cols'}, gapCard, questions),
    ...practice.map(practiceCard), progress, keys,
    button('Delete assignment and retained work', async () => {
      if (!window.confirm('Delete this assignment, all submissions, source pages, and review history?')) return;
      await api('/assignments/' + a.id, 'DELETE'); await home(); message('Assignment and retained work deleted.');
    }, 'danger')]);
}

function uploadCard(a) {
  const code = input('student-code', '', {required: true, pattern: '[A-Za-z0-9_-]{1,40}', maxLength: 40, placeholder: 'student-01'});
  const files = input('homework-files', '', {type: 'file', multiple: true, accept: 'image/jpeg,image/png,application/pdf'});
  const form = el('form', {onsubmit: event => {
    event.preventDefault();
    run(async () => {
      const selected = [...files.files];
      if (!selected.length) {
        const s = await api('/assignments/' + a.id + '/submissions', 'POST', {student_code: code.value});
        await openSubmission(s.id); message('Typed response created. Enter the work and confirm it.'); return;
      }
      if (selected.length > 20) throw new Error('Upload at most 20 students at a time.');
      if (selected.length > 1 && code.value.length > 36) throw new Error('Use a shorter code prefix for a batch.');
      for (let i = 0; i < selected.length; i++) {
        const file = selected[i];
        if (file.size > 8 * 1024 * 1024) throw new Error(file.name + ' exceeds 8 MiB. Earlier uploads, if any, are saved.');
        message('Uploading ' + (i + 1) + ' of ' + selected.length + '…');
        const encoded = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result).split(',')[1]);
          reader.onerror = () => reject(new Error('Could not read this file.'));
          reader.readAsDataURL(file);
        });
        await api('/assignments/' + a.id + '/uploads', 'POST', {
          student_code: selected.length === 1 ? code.value : code.value + '-' + String(i + 1).padStart(2, '0'),
          file_base64: encoded
        });
      }
      await dashboard(); message('Uploads saved. Open each response to extract or enter the work.');
    }, 'Preparing student work…');
  }}, el('div', {class: 'form-row'}, label('Anonymous student code / batch prefix', code), label('Homework files (optional)', files)),
    el('p', {class: 'footnote'}, 'One file per student. JPG/PNG up to 20 megapixels or PDF up to 5 pages; 8 MiB per file. Batch codes end in -01, -02, and so on. Leave files empty to enter a typed response.'),
    el('button', {type: 'submit'}, 'Add student work'));
  return el('div', {class: 'card'}, el('h2', {}, 'Add homework'), el('div', {class: 'upload-box'}, form),
    el('p', {class: 'footnote'}, 'Use anonymous codes and work you have permission to upload. Normalized source pages are retained until you delete the submission or assignment.'));
}

function assignmentForm() {
  const title = input('assignment-title', '', {required: true, maxLength: 256, placeholder: 'Week 3 · Algebra checkpoint'});
  const classroom = input('class-name', '', {required: true, maxLength: 256, placeholder: 'Algebra 1 · Period 2'});
  const questionArea = el('div', {}), cards = [];
  function addQuestion() {
    if (cards.length >= 5) return;
    const number = cards.length + 1, prefix = 'question-' + number;
    const equation = input(prefix + '-equation', '', {required: true, maxLength: 256, placeholder: '2(x+3)=10'});
    const answer = input(prefix + '-answer', '', {required: true, maxLength: 256, placeholder: 'x=2'});
    const skill = select(prefix + '-skill', [['linear', 'Linear equations'], ['distribution', 'Distribution'], ['quadratic', 'Quadratics']], 'linear');
    const answerPoints = input(prefix + '-answer-points', '3', {type: 'number', min: 1, max: 20, required: true});
    const workPoints = input(prefix + '-work-points', '2', {type: 'number', min: 0, max: 20, required: true});
    const manualPoints = input(prefix + '-manual-points', '0', {type: 'number', min: 0, max: 20, required: true});
    const manualLabel = input(prefix + '-manual-label', 'Teacher-reviewed reasoning', {maxLength: 256});
    cards.push({equation, answer, skill, answerPoints, workPoints, manualPoints, manualLabel});
    questionArea.append(el('fieldset', {class: 'question-builder'}, el('legend', {}, 'Question ' + number),
      el('div', {class: 'form-row'}, label('Equation ' + number, equation), label('Answer key ' + number, answer)),
      el('div', {class: 'form-row'}, label('Skill ' + number, skill), label('Final-answer points ' + number, answerPoints)),
      el('div', {class: 'form-row'}, label('Valid-work points ' + number, workPoints), label('Manual-review points ' + number, manualPoints)),
      label('Manual criterion label ' + number, manualLabel)));
  }
  addQuestion();
  const form = el('form', {class: 'card', onsubmit: event => {
    event.preventDefault();
    run(async () => {
      const questions = cards.map((q, i) => {
        const criteria = [{id: 'answer', label: 'Complete final answer', kind: 'final_answer', points: Number(q.answerPoints.value)}];
        if (Number(q.workPoints.value)) criteria.push({id: 'work', label: 'Valid intermediate work', kind: 'valid_work', points: Number(q.workPoints.value)});
        if (Number(q.manualPoints.value)) criteria.push({id: 'manual', label: q.manualLabel.value, kind: 'teacher_review', points: Number(q.manualPoints.value)});
        return {id: 'Q' + (i + 1), equation: q.equation.value, answer: q.answer.value, skill: q.skill.value, criteria};
      });
      const created = await api('/assignments', 'POST', {title: title.value, class_name: classroom.value, questions});
      await home(created.id); message('Assignment created. The answer keys passed algebra validation.');
    });
  }}, el('div', {class: 'form-row'}, label('Assignment title', title), label('Class / tutoring group', classroom)),
    el('p', {class: 'muted'}, 'Use one real variable x, linear or quadratic equations, and complete answer keys. For two roots, write x=-3 or x=3.'),
    questionArea, button('+ Add question (up to 5)', async () => addQuestion(), 'secondary'),
    el('div', {class: 'subtle-box'}, 'Final-answer points require every correct real solution. Valid-work points require equivalent steps and at least one intermediate equation. Award partial credit and subjective reasoning during review; valid alternative methods are accepted.'),
    el('div', {class: 'toolbar'}, el('button', {type: 'submit'}, 'Create assignment'), button('Cancel', dashboard, 'secondary')));
  frame([el('div', {class: 'eyebrow'}, 'SET THE EXPECTATIONS'), el('h1', {}, 'New assignment'), form]);
}

async function openSubmission(id) {
  state.submission = await api('/submissions/' + id);
  reviewView();
}
function reviewView() {
  const s = state.submission, a = state.assignment;
  const source = el('div', {class: 'card source-panel'}, el('h2', {}, 'Original work'));
  if (s.page_count) {
    const pageSelect = select('source-page', Array.from({length: s.page_count}, (_, i) => [String(i + 1), 'Page ' + (i + 1)]), '1');
    const image = el('img', {class: 'source-image', src: apiRoot + '/submissions/' + s.id + '/pages/1', alt: 'Uploaded homework source, page 1'});
    pageSelect.addEventListener('change', () => { image.src = apiRoot + '/submissions/' + s.id + '/pages/' + pageSelect.value; image.alt = 'Uploaded homework source, page ' + pageSelect.value; });
    source.append(label('Source page', pageSelect), image,
      button('Extract handwriting with AI', async () => {
        message('Reading handwriting. This can take up to a few minutes; no grade is released automatically.');
        state.submission = await api('/submissions/' + s.id + '/extract', 'POST', {revision: s.revision});
        reviewView(); message('AI transcription is a draft. Compare it with the original before confirming.');
      }, 'secondary'),
      el('p', {class: 'footnote'}, state.session.vision_mode === 'openai'
        ? 'Extraction sends these normalized pages to the configured AI provider. It must preserve mistakes, not solve the work.'
        : 'AI extraction is not configured. You can transcribe the uploaded source manually.'));
  } else source.append(el('div', {class: 'source-placeholder'}, 'Typed response', el('br'), 'No source image was uploaded.'));
  const controls = [];
  const transcript = el('form', {class: 'card', onsubmit: event => {
    event.preventDefault();
    run(async () => {
      const answers = controls.map(c => ({question_id: c.question.id,
        steps: c.steps.value.split('\n').map(line => line.trim()).filter(Boolean),
        source_page: c.page.value ? Number(c.page.value) : null,
        unreadable: c.unreadable.checked, note: c.note.value}));
      message('Checking the confirmed work against the rubric…');
      state.submission = await api('/submissions/' + s.id + '/transcript', 'POST', {revision: s.revision, confirmed: true, answers});
      reviewView(); message('Draft scores are ready for review. Nothing is finalized yet.');
    });
  }}, el('h2', {}, '1. Confirm the transcription'),
    el('p', {class: 'muted'}, 'Keep the student’s mistakes. Enter one equation per line, without repeating the printed question. Empty means no response.'));
  for (const question of a.questions) {
    const answer = s.answers.find(x => x.question_id === question.id);
    const steps = el('textarea', {id: 'steps-' + question.id, rows: 4, value: answer.steps.join('\n'), maxLength: 5140, spellcheck: false});
    const page = select('page-' + question.id, [['', 'Typed / no response on source'], ...Array.from({length: s.page_count}, (_, i) => [String(i + 1), 'Page ' + (i + 1)])], answer.source_page ? String(answer.source_page) : '');
    const unreadable = input('unreadable-' + question.id, '', {type: 'checkbox', checked: answer.unreadable});
    const note = input('note-' + question.id, answer.note, {maxLength: 500});
    controls.push({question, steps, page, unreadable, note});
    transcript.append(el('div', {class: 'transcript-question'}, el('h3', {}, question.id + ' · ', el('span', {class: 'equation'}, question.equation)),
      label('Student steps ' + question.id, steps), label('Source for ' + question.id, page),
      el('label', {class: 'check'}, unreadable, 'Unreadable / needs a teacher decision'), label('Transcription note ' + question.id, note)));
  }
  const confirm = input('confirm-source', '', {type: 'checkbox', required: true});
  transcript.append(el('label', {class: 'check'}, confirm, 'I checked these equations against the source or entered the typed response.'),
    el('button', {type: 'submit'}, s.status === 'approved' ? 'Revise transcription and invalidate approval' : 'Confirm transcription & check'));
  const right = el('div', {}, transcript);
  if (s.results.length) right.append(gradingCard(s));
  const history = el('details', {}, el('summary', {}, 'Review history'), el('div', {}));
  history.addEventListener('toggle', async () => {
    if (!history.open) return;
    try {
      const events = await api('/submissions/' + s.id + '/history');
      history.lastChild.replaceChildren(...events.map(e => el('p', {class: 'footnote'}, 'Version ' + e.revision + ' · ' + e.action.replaceAll('_', ' ') + ' · ' + new Date(e.created * 1000).toLocaleString())));
    } catch (error) { message(error.message, true); }
  });
  frame([button('← Back to assignment', dashboard, 'quiet'),
    el('div', {class: 'heading-row'}, el('div', {}, el('div', {class: 'eyebrow'}, a.title),
      el('h1', {}, s.student_code), el('p', {class: 'muted'}, 'Version ' + s.revision + ' · ' + s.message)), badge(s.status)),
    el('div', {class: 'review-layout'}, source, right), history,
    button('Delete response and source pages', async () => {
      if (!window.confirm('Delete this response, its source pages, and review history?')) return;
      await api('/submissions/' + s.id, 'DELETE'); await dashboard(); message('Response deleted.');
    }, 'danger')]);
}

function gradingCard(s) {
  const edits = [];
  const card = el('form', {class: 'card', onsubmit: event => {
    event.preventDefault();
    run(async () => {
      const questions = edits.map(e => ({question_id: e.result.question_id,
        scores: e.points.map(p => ({criterion_id: p.id, points: Number(p.control.value)})),
        category: e.category.value, feedback: e.feedback.value, reason: e.reason.value}));
      state.submission = await api('/submissions/' + s.id + '/approve', 'POST', {revision: s.revision, confirmed: true, questions});
      reviewView(); message('Approved. This result is now included in class summaries and exports.');
    });
  }}, el('h2', {}, s.status === 'approved' ? '2. Approved grades & feedback' : '2. Review suggested grades'),
    el('p', {class: 'muted'}, 'Scores follow your point rules. Review partial credit, subjective criteria, and any unsupported work. Explain every override.'));
  for (const result of s.results) {
    const section = el('div', {class: 'result-question'}, el('h3', {}, result.question_id + ' · ' + result.skill));
    if (result.check?.first_error_step) section.append(el('p', {class: 'error-tag'}, 'First invalid step: ' + result.check.first_error_step));
    if (result.needs_review) section.append(el('div', {class: 'subtle-box warning-box'}, 'No automatic score for one or more criteria. A teacher must decide.'));
    const points = [];
    for (const criterion of result.criteria) {
      const value = s.status === 'approved' ? result.scores[criterion.id] : criterion.suggested;
      const control = input('score-' + result.question_id + '-' + criterion.id, value === null ? '' : String(value),
        {type: 'number', required: true, min: 0, max: criterion.points, step: 1, disabled: s.status === 'approved'});
      points.push({id: criterion.id, control});
      section.append(el('div', {class: 'criterion'}, el('div', {}, el('strong', {}, criterion.label),
        el('small', {}, criterion.evidence)), label(result.question_id + ' ' + criterion.id + ' / ' + criterion.points, control)));
    }
    const categories = ['none', 'distribution', 'missing_root', 'extra_root', 'equivalence', 'incomplete', 'manual_review'];
    const category = select('category-' + result.question_id, categories.map(c => [c, c.replaceAll('_', ' ')]), result.category);
    const feedback = el('textarea', {id: 'feedback-' + result.question_id, rows: 3, maxLength: 1500, value: result.feedback});
    const reason = input('reason-' + result.question_id, result.reason || '', {maxLength: 1000, placeholder: 'Required when you change a suggestion or assign manual points'});
    if (s.status === 'approved') { category.disabled = true; feedback.disabled = true; reason.disabled = true; }
    edits.push({result, points, category, feedback, reason});
    section.append(label('Reviewed error category ' + result.question_id, category), label('Student feedback ' + result.question_id, feedback),
      label('Teacher decision / override reason ' + result.question_id, reason));
    card.append(section);
  }
  if (s.status !== 'approved') {
    const approve = input('confirm-grades', '', {type: 'checkbox', required: true});
    card.append(el('label', {class: 'check'}, approve, 'I reviewed the scores and feedback and approve this result.'),
      el('button', {type: 'submit'}, 'Approve grades & feedback'));
  } else card.append(link('Download approved feedback', '/submissions/' + s.id + '/feedback.txt'),
    el('p', {class: 'footnote'}, 'To revise a grade, reconfirm the transcript above. This invalidates the previous approval and keeps its history.'));
  return card;
}

function practiceCard(record) {
  const card = el('div', {class: 'card'}, el('div', {class: 'heading-row'}, el('h2', {}, 'Targeted practice · ' + record.skill),
    badge(record.approved ? 'approved' : 'grading_draft')),
    el('p', {class: 'muted'}, record.source === 'openai_checked' ? 'AI-proposed equations with independently checked answer keys.' : 'Varied practice from checked equation templates. No AI generation was used.'));
  for (const q of record.questions) card.append(el('div', {class: 'practice-question'},
    el('p', {class: 'equation'}, q.id + '. ' + q.equation), el('small', {}, 'Teacher answer key: ' + q.answer)));
  card.append(el('p', {class: 'footnote'}, 'Student downloads contain questions only. Review difficulty and skill fit before approving.'));
  card.append(record.approved ? link('Download student practice', '/practice/' + record.id + '/questions.txt') :
    button('Approve practice set', async () => { await api('/practice/' + record.id + '/approve', 'POST'); await dashboard(); message('Practice approved for sharing.'); }));
  return card;
}

async function createDemo() {
  message('Creating a synthetic, typed example assignment…');
  const criteria = [{id: 'answer', label: 'Complete final answer', kind: 'final_answer', points: 3},
    {id: 'work', label: 'Valid intermediate work', kind: 'valid_work', points: 2}];
  const questions = [
    {id: 'Q1', equation: '2(x+3)=10', answer: 'x=2', skill: 'distribution', criteria},
    {id: 'Q2', equation: '2x+5=17', answer: 'x=6', skill: 'linear', criteria},
    {id: 'Q3', equation: 'x^2=9', answer: 'x=-3 or x=3', skill: 'quadratic', criteria}
  ];
  const a = await api('/assignments', 'POST', {title: 'Demo · Algebra foundations', class_name: 'Synthetic example class', questions});
  const examples = [
    {code: 'demo-A', steps: [['2x+3=10', '2x=7'], ['2x=12', 'x=6'], ['x=3']]},
    {code: 'demo-B', steps: [['x+3=5', 'x=2'], ['2x=12', 'x=6'], ['x^2-9=0', 'x=-3 or x=3']]}
  ];
  for (const example of examples) {
    const s = await api('/assignments/' + a.id + '/submissions', 'POST', {student_code: example.code});
    await api('/submissions/' + s.id + '/transcript', 'POST', {revision: s.revision, confirmed: true,
      answers: questions.map((q, i) => ({question_id: q.id, steps: example.steps[i], source_page: null, unreadable: false, note: 'Synthetic typed developer example.'}))});
  }
  await home(a.id); message('Synthetic demo ready. Review and approve the two draft results to populate the class summary.');
}

run(async () => {
  state.session = await api('/session'); setAccount();
  if (state.session.authenticated) await home(); else loginView();
});
