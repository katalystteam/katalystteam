import test from 'node:test';
import assert from 'node:assert/strict';
import { GhlClient } from '../poll.mjs';
import { GithubState } from '../github-state.mjs';
import { prepareBackfill } from '../backfill.mjs';

test('backfill posts only inbound replies in range with historical labels and original dates', () => {
  const start = Date.parse('2026-06-01'), end = Date.parse('2026-09-22');
  const messages = [
    { id: 'out', direction: 'outbound', conversationId: 'thread', contactId: 'c', dateAdded: '2026-06-01T01:00:00Z' },
    { id: 'reply', direction: 'inbound', conversationId: 'thread', contactId: 'c', dateAdded: '2026-06-02T01:00:00Z', body: 'Interested' },
    { id: 'linked', direction: 'inbound', contactId: 'd', replyToMessageId: 'may-email', dateAdded: '2026-06-03T01:00:00Z', body: 'Details?' },
    { id: 'unknown', direction: 'inbound', contactId: 'e', dateAdded: '2026-06-03T01:00:00Z' },
    { id: 'old', direction: 'inbound', replyToMessageId: 'old-email', dateAdded: '2026-05-01T01:00:00Z' },
  ];
  const result = prepareBackfill(messages, [{ id: 'c', firstName: 'Alex' }], 'loc', start, end);
  assert.equal(result.alerts.length, 2); assert.equal(result.unlinked, 1);
  assert.match(result.alerts[0].title, /Historical.*Alex/);
  assert.match(result.alerts[0].description, /2026-06-02/);
  assert.match(result.alerts[0].description, /Interested/);
  assert.match(result.alerts[1].description, /GHL identifies this/);
});
test('a stable scroll cursor can return new pages until an empty terminal page', async () => {
  let calls = 0;
  const client = new GhlClient('token', 'location', async () => {
    calls++;
    return Response.json({ messages: calls < 4 ? [{ id: `m${calls}`, dateAdded: '2026-06-01T12:00:00Z' }] : [], nextCursor: 'stable-cursor' });
  });
  const messages = await client.messages(Date.parse('2026-06-01'), Date.parse('2026-06-02'), ['Email']);
  assert.equal(messages.length, 3); assert.equal(calls, 4);
});
test('backfill checkpoint uses a separate encrypted file and context', async () => {
  const args = { repo: 'org/repo', token: 'token', key: 'key', locationId: 'loc',
    fetcher: async url => url.includes('/git/ref/') ? Response.json({ object: { sha: 'head' } }) : new Response('', { status: 404 }) };
  const live = new GithubState(args), backfill = new GithubState({ ...args, namespace: 'email-backfill-2026-06' });
  assert.notEqual(live.path, backfill.path); assert.notEqual(live.context, backfill.context);
  assert.equal(await backfill.load(), null);
  await assert.rejects(live.load(), /refusing to reset/);
});

test('GHL HTTP failures expose only a safe status and category', async () => {
  const client = new GhlClient('secret-token', 'location', async () =>
    new Response('sensitive provider response', { status: 422 }));
  await assert.rejects(client.get('/private/path'), error => {
    assert.equal(error.name, 'GhlHttpError');
    assert.equal(error.status, 422);
    assert.equal(error.message, 'GHL request failed (422)');
    assert.doesNotMatch(error.message, /secret-token|private\/path|sensitive/);
    return true;
  });
});
