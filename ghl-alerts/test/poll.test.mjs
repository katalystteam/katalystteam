import test from 'node:test';
import assert from 'node:assert/strict';
import { randomBytes } from 'node:crypto';
import { encryptState, decryptState, GithubState } from '../github-state.mjs';
import { GhlClient, planPoll, sendPending } from '../poll.mjs';
import { deliver, slackMessage } from '../core.mjs';

const epoch = Date.parse('2026-09-21T00:00:00Z');
const sample = () => ({ contacts: [{ id: 'c1', firstName: 'Alex', tags: ['buyer','active'] }],
  opportunities: [{ id: 'o1', name: 'Buyer', pipelineStageId: 's1', status: 'open' }], messages: [] });
const baseline = () => planPoll(null, sample(), 'loc', epoch);

test('baseline does not flood Slack with old records or messages', () => {
  const input = sample(); input.messages = [{ id: 'old', body: 'old reply', dateAdded: new Date(epoch - 1).toISOString() }];
  const state = planPoll(null, input, 'loc', epoch);
  assert.equal(state.outbox.length, 0);
  assert.equal(Object.keys(state.contacts).length, 1);
});
test('detects contact and pipeline changes once, including later reversions', () => {
  const input = sample(); input.contacts[0].tags.push('new'); input.opportunities[0].pipelineStageId = 's2';
  const next = planPoll(baseline(), input, 'loc', epoch + 300000);
  assert.equal(next.outbox.length, 2);
  assert.match(next.outbox[0].description, /tags/);
  assert.match(next.outbox[1].description, /s2/);
  assert.equal(planPoll(next, input, 'loc', epoch + 600000).outbox.length, 2);
  assert.equal(planPoll(next, sample(), 'loc', epoch + 600000).outbox.length, 4);
});
test('array order is stable and absent records are not falsely called deleted or new', () => {
  const old = baseline(), input = sample(); input.contacts[0].tags.reverse();
  assert.equal(planPoll(old, input, 'loc', epoch + 1).outbox.length, 0);
  const absent = planPoll(old, { contacts: [], opportunities: [], messages: [] }, 'loc', epoch + 1);
  assert.equal(absent.outbox.length, 0);
  assert.equal(planPoll(absent, sample(), 'loc', epoch + 2).outbox.length, 0);
});
test('overlap recovers delayed messages without resending and includes activity entries', () => {
  const input = sample(); input.messages = [
    { id: 'm1', contactId: 'c1', direction: 'inbound', messageType: 'Email', body: 'Please send details', dateAdded: new Date(epoch + 1).toISOString() },
    { id: 'm2', body: 'Appointment booked', dateAdded: new Date(epoch + 2).toISOString() },
  ];
  const next = planPoll(baseline(), input, 'loc', epoch + 300000);
  assert.equal(next.outbox.length, 2); assert.match(next.outbox[0].description, /Please send details/);
  assert.equal(next.outbox[1].type, 'ConversationActivity');
  next.outbox = [];
  assert.equal(planPoll(next, input, 'loc', epoch + 600000).outbox.length, 0);
  assert.throws(() => planPoll(next, input, 'other', epoch + 1));
});
test('encrypted state hides private text and detects tampering or wrong key/context', () => {
  const key = randomBytes(32).toString('base64'), state = { body: 'private reply' };
  const encrypted = encryptState(state, key, 'context');
  assert.equal(encrypted.includes('private reply'), false);
  assert.deepEqual(decryptState(encrypted, key, 'context'), state);
  assert.throws(() => decryptState(encrypted, key, 'wrong'));
  assert.throws(() => decryptState(encrypted, randomBytes(32).toString('base64'), 'context'));
  const broken = JSON.parse(encrypted); broken.tag = randomBytes(16).toString('base64');
  assert.throws(() => decryptState(JSON.stringify(broken), key, 'context'));
});
test('outbox saves each acknowledged send and leaves failed alerts for retry', async () => {
  const state = { outbox: [{ key: 'a' }, { key: 'b' }] }, saves = [];
  await assert.rejects(sendPending(state, { save: async s => saves.push(structuredClone(s)) }, 'token', {
    send: async a => a.key === 'a' ? { ok: true } : { ok: false, code: 'not_in_channel' }, sleep: async () => {},
  }), /not_in_channel/);
  assert.equal(saves.length, 1); assert.deepEqual(state.outbox, [{ key: 'b' }]);
  await assert.rejects(sendPending(state, { save: async () => { throw new Error('save failed'); } }, 'token', {
    send: async () => ({ ok: true }), sleep: async () => {},
  }), /save failed/);
});
test('message export explicitly requests email as well as other channels and follows cursor', async () => {
  const calls = [];
  const client = new GhlClient('token', 'loc', async url => {
    const p = new URL(url).searchParams; calls.push(p);
    const id = p.get('channel') === 'Email' ? p.get('cursor') ? 'email2' : 'email1' : 'sms';
    return Response.json({ messages: [{ id, dateAdded: new Date(epoch + 1).toISOString() }], nextCursor: id === 'email1' ? 'next' : null });
  });
  assert.equal((await client.messages(epoch, epoch + 1000)).length, 3);
  assert.deepEqual(calls.map(p => p.get('channel')), ['Email','Email',null]);
  assert.equal(calls[1].get('cursor'), 'next');
});
test('repeating/incomplete API pagination fails without advancing checkpoint', async () => {
  const client = new GhlClient('token', 'loc', async () => Response.json({ contacts: Array.from({ length: 100 }, (_,i) => ({ id: String(i), dateAdded: '2026-01-01' })) }));
  await assert.rejects(client.contacts(), /pagination repeated/);
  const messages = new GhlClient('token', 'loc', async () => Response.json({ messages: [{ id: 'same', dateAdded: new Date(epoch).toISOString() }], nextCursor: 'same' }));
  await assert.rejects(messages.messages(epoch, epoch + 1000), /pagination incomplete/);
});
test('existing state branch with missing checkpoint fails closed', async () => {
  const store = new GithubState({ repo: 'org/repo', locationId: 'loc', token: 'token', key: randomBytes(32).toString('base64'),
    fetcher: async url => url.includes('/git/ref/') ? Response.json({ object: { sha: 'head' } }) : new Response('', { status: 404 }) });
  await assert.rejects(store.load(), /refusing to reset/);
});
test('Slack destination is fixed, mentions escaped, API failures detected', async () => {
  const a = { title: 'New reply', description: '<!channel> hello', type: 'InboundMessage' };
  const payload = slackMessage(a);
  assert.equal(payload.channel, 'C0BQK1SQ2RM'); assert.equal(payload.mrkdwn, false);
  assert.equal(payload.text.includes('<!channel>'), false); assert.equal(payload.blocks[1].text.type, 'plain_text');
  assert.equal((await deliver(a, 'token', async () => new Response('', { status: 429, headers: { 'retry-after': '10' } }))).retryMs, 10000);
  assert.equal((await deliver(a, 'token', async () => Response.json({ ok: false, error: 'invalid_auth' }))).permanent, true);
});
