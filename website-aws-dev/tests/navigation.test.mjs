import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const pages = [
  ['index.html', 'Home'],
  ['demos/index.html', 'Analyzer'],
  ['library/index.html', 'My Analyses'],
  ['feedback/index.html', 'Feedback']
];
const expected = [
  ['/', 'Home'], ['/#features', 'Features'],
  ['/#how-it-works', 'How it works'], ['/demos/', 'Analyzer'],
  ['/library/', 'My Analyses'], ['/feedback/', 'Feedback']
];
const navHTML = (src, pattern) => {
  const found = src.match(pattern);
  assert.ok(found, 'all pages must include the menu');
  return found[1];
};
function links(src) {
  return [...src.matchAll(/<a href="([^"]+)"(?: aria-current="page")?>([^<]+)<\/a>/g)]
    .map(match => [match[1], match[2]]);
}
test('top navigation, mobile navigation, and analyzer CTA remain identical across every page', () => {
  for (const [path,active] of pages) {
    const html = readFileSync(new URL('../' + path, import.meta.url), 'utf8');
    const desktop = navHTML(html, /<nav class="main-nav" aria-label="Primary navigation">([\s\S]*?)<\/nav>/);
    const mobile = navHTML(html, /<nav id="mobile-nav" class="mobile-nav" aria-label="Mobile navigation">([\s\S]*?)<\/nav>/);
    assert.deepEqual(links(desktop), expected, 'desktop menu changes on ' + path);
    assert.deepEqual(links(mobile), expected, 'mobile menu changes on ' + path);
    assert.equal((desktop.match(/aria-current="page"/g) || []).length, 1);
    assert.equal((mobile.match(/aria-current="page"/g) || []).length, 1);
    assert.match(desktop, new RegExp('<a href="[^"]+" aria-current="page">' + active + '<\\/a>'));
    assert.match(mobile, new RegExp('<a href="[^"]+" aria-current="page">' + active + '<\\/a>'));
    assert.match(html, /<a class="pill pill-coral" href="\/demos\/#analysis-studio">Try analyzer/);
    assert.doesNotMatch(desktop, /AWS analyzer|Live website/);
  }
});
