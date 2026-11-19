import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const page = readFileSync(new URL('../library/index.html', import.meta.url), 'utf8');
const owner = readFileSync(new URL('../assets/library.js', import.meta.url), 'utf8');
const publicFeed = readFileSync(new URL('../assets/community-feed.js', import.meta.url), 'utf8');
const api = readFileSync(new URL('../../strokesense/aws_app/handler.py', import.meta.url), 'utf8');

test('library keeps private and public community videos in separate accessible tabs', () => {
  for (const id of ['library-tab-private', 'library-tab-community', 'library-private-section',
    'library-community-section', 'community-list', 'community-video-player']) {
    assert.match(page, new RegExp('id="' + id + '"'));
  }
  assert.match(page, /id="library-community-section"[^>]+hidden/);
  assert.match(page, /src="\/assets\/community-feed\.js"/);
  assert.match(page, /Shared by their owners/);
});

test('owner public sharing is opt in and independent from admin review consent', () => {
  assert.match(owner, /\/analysis\/jobs\/' \+ encodeURIComponent\(job\.job_id\) \+ '\/publish'/);
  assert.match(owner, /window\.confirm/);
  assert.match(owner, /public: next/);
  assert.match(owner, /job\.community_shared === true/);
  assert.match(owner, /allow_admin_review/);
  assert.match(owner, /Unpublish video/);
});

test('anonymous community browsing never uses browser auth token or raw user identifiers', () => {
  assert.match(publicFeed, /\/community\/videos/);
  assert.match(publicFeed, /credentials: 'omit'/);
  assert.doesNotMatch(publicFeed, /sessionStorage|Authorization:|accessToken|\.innerHTML\s*=/);
  assert.doesNotMatch(publicFeed, /video\.filename|video\.user_id|report_html/);
  assert.match(publicFeed, /X-Amz-Signature/);
  assert.match(publicFeed, /community-video-player/);
});

test('public APIs remain explicit separate routes before the Cognito requirement', () => {
  const list = api.indexOf('if method == "GET" and path == "/community/videos"');
  const auth = api.indexOf('user_id = _user_id(event)');
  const publish = api.indexOf('COMMUNITY_PUBLISH_ROUTE.fullmatch(path)');
  assert.ok(list > 0 && list < auth && publish > auth);
});
