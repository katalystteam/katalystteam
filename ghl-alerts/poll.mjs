import { createHash } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import { cleanMessage, normalize, deliver } from './core.mjs';
import { GithubState } from './github-state.mjs';

const pause = (ms) => new Promise(resolve => setTimeout(resolve, ms));
const canonical = (v) => Array.isArray(v) ? `[${v.map(canonical).sort().join(',')}]`
  : v && typeof v === 'object' ? `{${Object.keys(v).sort().map(k => `${JSON.stringify(k)}:${canonical(v[k])}`).join(',')}}`
    : JSON.stringify(v);
const hash = (value) => createHash('sha256').update(canonical(value)).digest('hex');
const nameOf = (r) => r.name || r.contactName || [r.firstName || r.firstNameLowerCase, r.lastName || r.lastNameLowerCase].filter(Boolean).join(' ') || r.contactId || r.id;

export class GhlClient {
  constructor(token, locationId, fetcher = fetch) { this.token = token; this.locationId = locationId; this.fetcher = fetcher; }
  async get(path, params = {}) {
    const query = new URLSearchParams(Object.entries(params).filter(([,v]) => v !== undefined).map(([k,v]) => [k, String(v)]));
    for (let attempt = 0; attempt < 4; attempt++) {
      const response = await this.fetcher(`https://services.leadconnectorhq.com${path}?${query}`, {
        redirect: 'error', signal: AbortSignal.timeout(30_000),
        headers: { Authorization: `Bearer ${this.token}`, Version: '2021-07-28', Accept: 'application/json' },
      });
      if (response.ok) return response.json();
      if ((response.status === 429 || response.status >= 500) && attempt < 3) {
        const delay = Number(response.headers.get('retry-after')) * 1000 || 1000 * 2 ** attempt;
        if (delay > 30_000) throw new Error('GHL requested a long retry; next scheduled run will retry');
        await pause(delay); continue;
      }
      const error = new Error(`GHL request failed (${response.status})`); // no paths, bodies, or tokens in logs
      error.name = 'GhlHttpError';
      error.status = response.status;
      throw error;
    }
  }
  async updateContactEmail(contactId, email) {
    if (!/^[A-Za-z0-9_-]+$/.test(contactId || '')) throw new Error('Invalid contact ID');
    const response = await this.fetcher(`https://services.leadconnectorhq.com/contacts/${contactId}`, {
      method: 'PUT', redirect: 'error', signal: AbortSignal.timeout(30_000),
      headers: { Authorization: `Bearer ${this.token}`, Version: '2021-07-28', Accept: 'application/json',
        'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    });
    if (!response.ok) {
      const error = new Error(`GHL contact update failed (${response.status})`);
      error.name = 'GhlHttpError'; error.status = response.status; throw error;
    }
    const data = await response.json();
    if (data.succeeded === false || (data.contact && data.contact.email?.toLowerCase() !== email.toLowerCase())) {
      throw new Error('GHL did not confirm the contact email update');
    }
    return data;
  }
  async contacts() {
    const result = []; const seen = new Set(); let cursor;
    for (let page = 0; page < 500; page++) {
      const data = await this.get('/contacts/', { locationId: this.locationId, limit: 100, ...cursor });
      if (!Array.isArray(data.contacts)) throw new Error('Invalid contact response');
      for (const c of data.contacts) {
        if (!c.id || seen.has(c.id)) throw new Error('Contact pagination repeated/missing record; checkpoint unchanged');
        if (c.locationId && c.locationId !== this.locationId) throw new Error('Unexpected contact location');
        seen.add(c.id); result.push(c);
      }
      if (data.contacts.length < 100) return result;
      const last = data.contacts.at(-1);
      const startAfter = data.meta?.startAfter ?? Date.parse(last.dateAdded);
      if (!Number.isFinite(Number(startAfter))) throw new Error('Contact cursor missing');
      cursor = { startAfter, startAfterId: data.meta?.startAfterId || last.id };
    }
    throw new Error('Contact scan exceeded 50,000 records; checkpoint unchanged');
  }
  async opportunities() {
    const result = []; const seen = new Set();
    for (let page = 1; page <= 500; page++) {
      const data = await this.get('/opportunities/search', { location_id: this.locationId, status: 'all', page, limit: 100 });
      if (!Array.isArray(data.opportunities)) throw new Error('Invalid opportunity response');
      for (const o of data.opportunities) {
        if (!o.id || seen.has(o.id)) throw new Error('Opportunity pagination repeated/missing record; checkpoint unchanged');
        if (o.locationId && o.locationId !== this.locationId) throw new Error('Unexpected opportunity location');
        seen.add(o.id); result.push(o);
      }
      if (data.opportunities.length < 100) return result;
    }
    throw new Error('Opportunity scan exceeded 50,000 records; checkpoint unchanged');
  }
  async messages(since, until, channels = ['Email', undefined]) {
    const result = new Map();
    // Omitting channel excludes email. Both exports are required.
    for (const channel of channels) {
      let cursor; const pages = new Set();
      for (let page = 0; page < 500; page++) {
        const data = await this.get('/conversations/messages/export', {
          locationId: this.locationId, channel, startDate: new Date(since).toISOString(),
          endDate: new Date(until).toISOString(), sortBy: 'createdAt', sortOrder: 'asc', limit: 500, cursor,
        });
        if (!Array.isArray(data.messages)) throw new Error('Invalid message export response');
        if (data.messages.length === 0) break;
        const pageKey = hash(data.messages.map(m => m.id));
        if (pages.has(pageKey)) throw new Error('Message pagination incomplete');
        pages.add(pageKey);
        for (const m of data.messages) {
          if (!m.id) throw new Error('Message ID missing');
          if (m.locationId && m.locationId !== this.locationId) throw new Error('Unexpected message location');
          const date = Date.parse(m.dateAdded);
          if (!Number.isFinite(date)) throw new Error('Message date missing');
          if (date >= since && date <= until) result.set(m.id, { ...m, messageType: m.messageType || channel || 'Activity' });
        }
        if (!data.nextCursor) break;
        if (page === 499) throw new Error('Message pagination incomplete');
        cursor = data.nextCursor;
      }
    }
    return [...result.values()].sort((a,b) => Date.parse(a.dateAdded) - Date.parse(b.dateAdded));
  }
}

const emailPattern = /[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+/gi;
export function analyzeEmailChange(message, currentEmail = '') {
  if (message?.direction !== 'inbound') return { reason: 'not_inbound' };
  if (String(message.messageType).toLowerCase() !== 'email') return { reason: 'not_email' };
  const body = cleanMessage(message.body, 2400);
  const intent = /\b(?:new|updated|current|preferred|different)\s+e-?mail(?:\s+address)?\b|\b(?:update|change|replace)\s+(?:my|our|the)?\s*e-?mail|\bupdate\s+(?:your|the)\s+(?:records|contact info)/i;
  if (!intent.test(body)) return { reason: 'no_intent' };
  const existing = String(currentEmail).trim().toLowerCase();
  const candidates = [...new Set((body.match(emailPattern) || []).map(value => value.toLowerCase().replace(/[.,;:!?]+$/, '')))]
    .filter(value => value !== existing);
  return candidates.length === 1 ? { email: candidates[0], reason: 'eligible' } : { reason: candidates.length ? 'ambiguous_addresses' : 'no_replacement_address' };
}
export function detectEmailChange(message, currentEmail = '') {
  return analyzeEmailChange(message, currentEmail).email || null;
}

export async function applyEmailChanges(client, contacts, messages, previous, { write = true } = {}) {
  const byId = new Map(contacts.map(contact => [contact.id, contact]));
  const owners = new Map(contacts.filter(contact => contact.email).map(contact => [contact.email.toLowerCase(), contact.id]));
  const stats = { detected: 0, updated: 0, conflicts: 0 };
  if (!previous) return stats;
  for (const message of messages) {
    const messageHash = hash(message.id);
    if (Date.parse(message.dateAdded) < previous.baselineAt || previous.seen?.[messageHash]) continue;
    const contact = byId.get(message.contactId);
    if (!contact) continue;
    const email = detectEmailChange(message, contact.email);
    if (!email) continue;
    stats.detected++;
    const owner = owners.get(email);
    if (owner && owner !== contact.id) {
      stats.conflicts++;
      message.automationNote = 'Contact email was not changed because that address already belongs to another contact.';
      continue;
    }
    if (write) {
      await client.updateContactEmail(contact.id, email);
      owners.delete(String(contact.email || '').toLowerCase()); owners.set(email, contact.id);
      contact.email = email; contact._automatedEmailUpdate = true; stats.updated++;
      message.automationNote = `Contact email updated to ${email}.`;
    } else message.automationNote = `Dry run: contact email would be updated to ${email}.`;
  }
  return stats;
}

const fields = {
  contacts: ['firstName','lastName','name','email','phone','companyName','address1','city','state','postalCode','country','tags','dnd','dndSettings','assignedTo','customFields','source','type'],
  opportunities: ['name','pipelineId','pipelineStageId','status','assignedTo','monetaryValue','contactId','customFields'],
};
export function snapshot(records, kind) {
  return Object.fromEntries(records.map(r => [hash(r.id), Object.fromEntries(fields[kind].map(k => [k, canonical(r[k] ?? null)]))]));
}

export function planPoll(previous, { contacts, opportunities, messages }, locationId, until) {
  const next = previous ? structuredClone(previous) : {
    version: 1, location: hash(locationId), baselineAt: until, seen: {}, outbox: [],
  };
  if (next.version !== 1 || next.location !== hash(locationId) || !Array.isArray(next.outbox)) throw new Error('Checkpoint schema/location mismatch');
  const current = { contacts: snapshot(contacts, 'contacts'), opportunities: snapshot(opportunities, 'opportunities') };
  if (previous) {
    const queued = new Set(next.outbox.map(a => a.key));
    const append = (alert) => { if (!queued.has(alert.key)) { queued.add(alert.key); next.outbox.push(alert); } };
    for (const kind of ['contacts', 'opportunities']) {
      for (const record of kind === 'contacts' ? contacts : opportunities) {
        const id = hash(record.id), before = previous[kind]?.[id], after = current[kind][id];
        const changed = before ? Object.keys(after).filter(k => before[k] !== after[k]) : [];
        if (before && changed.length === 0) continue;
        if (record._automatedEmailUpdate && changed.length === 1 && changed[0] === 'email') continue;
        const type = kind === 'contacts' ? before ? 'ContactUpdate' : 'ContactCreate'
          : !before ? 'OpportunityCreate' : changed.includes('pipelineStageId') || changed.includes('pipelineId') ? 'OpportunityStageUpdate'
            : changed.includes('status') ? 'OpportunityStatusUpdate' : 'OpportunityUpdate';
        const alert = normalize({ ...record, name: nameOf(record), type, locationId,
          webhookId: `poll:${kind}:${id}:${until}`, timestamp: new Date(until).toISOString() });
        if (before) alert.description += `\nChanged fields: ${changed.join(', ')}. Detected during periodic check.`;
        append(alert);
      }
    }
    const names = new Map(contacts.map(c => [c.id, nameOf(c)]));
    for (const message of messages) {
      const key = hash(message.id);
      if (Date.parse(message.dateAdded) < next.baselineAt || next.seen[key]) continue;
      const type = message.direction === 'inbound' ? 'InboundMessage' : message.direction === 'outbound' ? 'OutboundMessage' : 'ConversationActivity';
      const alert = normalize({ ...message, type, locationId,
        name: names.get(message.contactId) || message.contactId || message.id,
        webhookId: `message:${message.id}`, timestamp: message.dateAdded });
      if (message.automationNote) alert.description += `\n${message.automationNote}`;
      if (type === 'ConversationActivity' && message.body) alert.description = String(message.body).slice(0, 2500);
      append(alert); next.seen[key] = until;
    }
  }
  // Keep unseen/missing records in the fingerprint snapshot. Absence in a scan
  // is not reliable evidence of deletion, and later reappearance is not creation.
  next.contacts = { ...previous?.contacts, ...current.contacts };
  next.opportunities = { ...previous?.opportunities, ...current.opportunities };
  next.until = until;
  // Message export overlaps 24 hours to tolerate delayed indexing. Retain IDs
  // longer than the overlap; pending alerts retain their own identity.
  next.seen = Object.fromEntries(Object.entries(next.seen).filter(([,time]) => time >= until - 7 * 86_400_000));
  return next;
}

export async function sendPending(state, store, token, { send = deliver, sleep = pause, limit = 100 } = {}) {
  let sent = 0;
  while (state.outbox.length && sent < limit) {
    const result = await send(state.outbox[0], token);
    if (!result.ok) throw new Error(`Slack delivery deferred: ${result.code}. Pending alert remains encrypted for next run.`);
    state.outbox.shift();
    await store.save(state); // commit each acknowledged message before sending another
    sent++;
    await sleep(1100);
  }
  return sent;
}

async function main(env = process.env) {
  const mode = env.ALERT_MODE || 'poll';
  if (!['poll','dry-run','test-slack'].includes(mode)) throw new Error('Invalid ALERT_MODE');
  for (const key of ['GHL_API_TOKEN','GHL_LOCATION_ID','GITHUB_TOKEN','GITHUB_REPOSITORY','ALERT_STATE_KEY']) {
    if (!env[key]) throw new Error(`Missing ${key}`);
  }
  if (mode !== 'dry-run' && !env.SLACK_BOT_TOKEN?.startsWith('xoxb-')) throw new Error('Missing SLACK_BOT_TOKEN');
  const store = new GithubState({ repo: env.GITHUB_REPOSITORY, token: env.GITHUB_TOKEN,
    key: env.ALERT_STATE_KEY, locationId: env.GHL_LOCATION_ID });
  const previous = await store.load();
  if (mode === 'test-slack') {
    const result = await deliver({ title: 'TEST — GHL activity alerts',
      description: 'GitHub Actions can post to this channel. This test does not enable or verify GHL monitoring.',
      type: 'DeliveryTest', occurredAt: new Date().toISOString() }, env.SLACK_BOT_TOKEN);
    if (!result.ok) throw new Error(`Slack test failed: ${result.code}`);
    console.log('Slack delivery test succeeded'); return;
  }
  const client = new GhlClient(env.GHL_API_TOKEN, env.GHL_LOCATION_ID);
  if (mode === 'poll' && previous?.outbox.length) {
    await sendPending(previous, store, env.SLACK_BOT_TOKEN);
    if (previous.outbox.length) { console.log('Backlog retained; collection resumes after delivery'); return; }
  }
  const until = Date.now();
  const since = previous ? Math.max(previous.baselineAt, previous.until - 86_400_000) : until - 300_000;
  const contacts = await client.contacts();
  const opportunities = await client.opportunities();
  const messages = await client.messages(since, until);
  const emailAutomation = await applyEmailChanges(client, contacts, messages, previous, { write: mode === 'poll' });
  const next = planPoll(previous, { contacts, opportunities, messages }, env.GHL_LOCATION_ID, until);
  console.log(JSON.stringify({ mode, baseline: !previous, contacts: contacts.length, opportunities: opportunities.length,
    messagesScanned: messages.length, pendingAlerts: next.outbox.length, emailAutomation }));
  if (mode === 'dry-run') { console.log('Dry run: no messages sent and no checkpoint saved'); return; }
  await store.save(next); // snapshot and outbox become durable before the first Slack send
  const sent = await sendPending(next, store, env.SLACK_BOT_TOKEN);
  console.log(JSON.stringify({ sent, pending: next.outbox.length }));
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch(error => { console.error(error.message); process.exitCode = 1; });
}
