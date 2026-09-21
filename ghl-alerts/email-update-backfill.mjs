import { createHash } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import { cleanMessage, deliver } from './core.mjs';
import { GithubState } from './github-state.mjs';
import { analyzeEmailChange, GhlClient } from './poll.mjs';
import { loadHistoricalEmails } from './backfill.mjs';

const hash = value => createHash('sha256').update(String(value)).digest('hex');
const nameOf = contact => cleanMessage(contact.name || [contact.firstName, contact.lastName].filter(Boolean).join(' ') || contact.id, 100);

function validate(state, start) {
  if (!state || state.version !== 1 || state.since !== start || !state.processed || !Array.isArray(state.updates)) {
    throw new Error('Invalid email-update backfill checkpoint');
  }
}

function listChunks(updates) {
  const lines = updates.map(row => `- ${row.name}: ${row.email}`);
  const chunks = [];
  for (let index = 0; index < lines.length; index += 20) chunks.push(lines.slice(index, index + 20).join('\n'));
  return chunks.length ? chunks : ['No eligible contact email changes were found.'];
}

export async function runEmailUpdateBackfill(env = process.env) {
  const mode = env.EMAIL_UPDATE_BACKFILL_MODE || 'apply';
  if (!['inspect', 'apply'].includes(mode)) throw new Error('Invalid email-update backfill mode');
  for (const key of ['GHL_API_TOKEN', 'GHL_LOCATION_ID', 'GITHUB_TOKEN', 'GITHUB_REPOSITORY', 'ALERT_STATE_KEY']) {
    if (!env[key]) throw new Error(`Missing ${key}`);
  }
  if (mode === 'apply' && !env.SLACK_BOT_TOKEN?.startsWith('xoxb-')) throw new Error('Missing SLACK_BOT_TOKEN');
  const start = Date.parse('2026-03-01T00:00:00+08:00');
  const args = { repo: env.GITHUB_REPOSITORY, token: env.GITHUB_TOKEN, key: env.ALERT_STATE_KEY, locationId: env.GHL_LOCATION_ID };
  const store = new GithubState({ ...args, namespace: 'email-contact-update-backfill-2026-03-v1' });
  let state = await store.load();
  const end = state?.until || Date.now();
  const client = new GhlClient(env.GHL_API_TOKEN, env.GHL_LOCATION_ID);
  const emails = await loadHistoricalEmails(client, start, end);
  const contacts = await client.contacts();
  const byId = new Map(contacts.map(contact => [contact.id, contact]));
  const owners = new Map(contacts.filter(contact => contact.email).map(contact => [contact.email.toLowerCase(), contact.id]));
  state ||= { version: 1, since: start, until: end, processed: {}, updates: [], conflicts: 0, summaryIndex: 0 };
  validate(state, start);
  let detected = 0; let updated = 0; let conflicts = 0; const eligibility = {};
  for (const message of emails) {
    if (message.direction !== 'inbound' || Date.parse(message.dateAdded) < start) continue;
    const id = hash(message.id);
    if (state.processed[id]) continue;
    const contact = byId.get(message.contactId);
    const analysis = contact ? analyzeEmailChange(message, contact.email) : { reason: 'contact_missing' };
    eligibility[analysis.reason] = (eligibility[analysis.reason] || 0) + 1;
    const email = analysis.email;
    if (!email) { state.processed[id] = 'not_eligible'; continue; }
    detected++;
    const owner = owners.get(email);
    if (owner && owner !== contact.id) {
      state.processed[id] = 'conflict'; state.conflicts++; conflicts++;
      await store.save(state); continue;
    }
    if (mode === 'inspect') continue;
    await client.updateContactEmail(contact.id, email);
    owners.delete(String(contact.email || '').toLowerCase()); owners.set(email, contact.id); contact.email = email;
    state.processed[id] = 'updated';
    state.updates.push({ name: nameOf(contact), email, occurredAt: message.dateAdded });
    await store.save(state); updated++;
  }
  console.log(JSON.stringify({ mode, emails: emails.length, contacts: contacts.length, detected, updated, eligibility,
    conflicts, alreadyProcessed: Object.keys(state.processed).length, totalUpdated: state.updates.length,
    totalConflicts: state.conflicts, since: new Date(start).toISOString(), until: new Date(end).toISOString() }));
  if (mode !== 'apply') return;
  const chunks = listChunks(state.updates);
  while (state.summaryIndex < chunks.length) {
    const index = state.summaryIndex;
    const result = await deliver({ type: 'ContactEmailUpdateBackfill', occurredAt: new Date(end).toISOString(),
      title: `Contact email updates: March 2026 onward (${index + 1}/${chunks.length})`, description: chunks[index] }, env.SLACK_BOT_TOKEN);
    if (!result.ok) throw new Error(`Slack email-update list delivery failed: ${result.code}`);
    state.summaryIndex++;
    await store.save(state);
  }
  console.log(JSON.stringify({ listMessagesPosted: chunks.length, listEntries: state.updates.length }));
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  runEmailUpdateBackfill().catch(error => {
    const status = Number.isInteger(error?.status) ? { status: error.status } : {};
    console.error(JSON.stringify({ event: 'email_update_backfill_failed', category: error?.name === 'GhlHttpError' ? 'ghl_http' : 'internal', ...status }));
    process.exitCode = 1;
  });
}
