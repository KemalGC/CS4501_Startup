import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const library = readFileSync(new URL('../assets/library.js', import.meta.url), 'utf8');
const analyzer = readFileSync(new URL('../assets/aws-client.js', import.meta.url), 'utf8');
const page = readFileSync(new URL('../demos/index.html', import.meta.url), 'utf8');

test('upload accepts a custom display name while preserving the actual video bytes', () => {
  assert.match(page, /id="upload-display-name"/);
  assert.match(page, /maxlength="128"/);
  assert.match(analyzer, /ui\.displayName\.value = file\.name\.slice\(0, 128\)/);
  assert.match(analyzer, /filename: chosenName/);
  assert.match(analyzer, /const parts = await uploadMultipart\(upload, abortController\.signal, sourceFile\)/);
});

test('My Analyses presents inline rename and saves it to the owner-only API', () => {
  assert.match(library, /const rename = node\('button', 'library-rename-button', 'Rename'\)/);
  assert.match(library, /editor\.hidden = !editor\.hidden/);
  assert.match(library, /\/analysis\/jobs\/' \+ encodeURIComponent\(job\.job_id\) \+ '\/rename'/);
  assert.match(library, /headers: \{ Authorization: 'Bearer ' \+ auth\.accessToken/);
  assert.match(library, /title\.textContent = displayFilename\(job\.filename\)/);
  assert.match(library, /filename: name/);
  assert.doesNotMatch(library, /innerHTML\s*=/);
});
