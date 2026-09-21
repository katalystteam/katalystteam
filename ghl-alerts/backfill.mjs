import { createHash } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import { GhlClient } from './poll.mjs';
import { GithubState } from './github-state.mjs';
import { cleanMessage, normalize, deliver } from './core.mjs';

const digest = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');
const safeFailure = (error, phase) => ({
  phase,
  category: error?.name === 'GhlHttpError' ? 'ghl_http' : error?.name === 'AbortError' ? 'timeout' : 'internal',
  ...(Number.isInteger(error?.status) ? { status: error.status } : {}),
});
export async function loadHistoricalEmails(client, start, end, log = console.log) {
  const emails = new Map();
  const windowMs = 7 * 86_400_000;
  for (let from = start, window = 1; from <= end; window++) {
    const to = Math.min(end, from + windowMs - 1);
    const batch = await client.messages(from, to, ['Email']);
    for (const message of batch) emails.set(message.id, message);
    log(JSON.stringify({ event: 'historical_export_progress', window,
      from: new Date(from).toISOString(), to: new Date(to).toISOString(), records: batch.length,
      recordsTotal: emails.size }));
    from = to + 1;
  }
  return [...emails.values()].sort((a,b) => Date.parse(a.dateAdded) - Date.parse(b.dateAdded));
}
export function prepareBackfill(emails, contacts, locationId, since, until) {
  const names = new Map(contacts.map(c => [c.id, c.name || [c.firstName, c.lastName].filter(Boolean).join(' ') || c.email || c.id]));
  const outbound = new Map();
  const alerts = []; let unlinked = 0;
  const seen = new Set();
  for (const m of [...emails].sort((a,b) => Date.parse(a.dateAdded) - Date.parse(b.dateAdded))) {
    if (seen.has(m.id)) continue;
    seen.add(m.id);
    const thread = m.conversationId || m.contactId;
    if (m.direction === 'outbound') { if (thread) outbound.set(thread, m); continue; }
    if (m.direction !== 'inbound' || Date.parse(m.dateAdded) < since || Date.parse(m.dateAdded) > until) continue;
    const parent = thread && outbound.get(thread);
    if (!m.replyToMessageId && !parent) { unlinked++; continue; }
    const alert = normalize({ ...m, type: 'InboundMessage', locationId,
      name: names.get(m.contactId) || m.from || m.contactId || 'Unknown contact',
      messageType: 'Email', webhookId: `message:${m.id}`, timestamp: m.dateAdded });
    alert.type = 'HistoricalEmailReply';
    alert.title = [...`Email reply: ${names.get(m.contactId) || m.from || m.contactId || 'Unknown contact'}`].slice(0,150).join('');
    const subject = cleanMessage(m.subject, 140);
    const preview = cleanMessage(m.body, 420);
    alert.description = `${subject ? `Subject: ${subject}\n` : ''}${preview || 'No message preview available.'}`;
    alert.description = [...alert.description].slice(0,2800).join('');
    alert.messageHash = digest(m.id);
    alerts.push(alert);
  }
  return { alerts, unlinked };
}

async function main(env = process.env) {
  const mode = env.BACKFILL_MODE || 'inspect';
  if (!['inspect','diagnose','post'].includes(mode)) throw new Error('Invalid backfill mode');
  const client = new GhlClient(env.GHL_API_TOKEN, env.GHL_LOCATION_ID);
  const args = { repo: env.GITHUB_REPOSITORY, token: env.GITHUB_TOKEN, key: env.ALERT_STATE_KEY, locationId: env.GHL_LOCATION_ID };
  const store = new GithubState({ ...args, namespace: 'email-backfill-2026-06' });
  let state = await store.load();
  const start = Date.parse('2026-06-01T00:00:00+08:00');
  const end = state?.until || Date.now();
  const emails = await loadHistoricalEmails(client, start, end);
  const inbound = emails.filter(m => m.direction === 'inbound');
  console.log(JSON.stringify({ emails: emails.length, inbound: inbound.length, people: new Set(inbound.map(m => m.contactId)).size,
    directReplyReferences: inbound.filter(m => m.replyToMessageId).length,
    nestedEmailIds: inbound.filter(m => m.meta?.email?.email?.messageIds?.length || m.meta?.email?.messageIds?.length).length,
    bodyAvailable: inbound.filter(m => m.body).length }));
  // Try the email endpoint for reply references, subjects and complete bodies.
  // A missing email object is not evidence of a reply; conversation ordering is
  // the fallback and is described explicitly in the Slack alert.
  let enriched = 0; const detailFailures = {}; let detailIdsMissing = 0;
  for (const m of inbound) {
    // The export message ID is not accepted by the email-detail endpoint. Only
    // use the email-specific IDs GHL supplies in metadata; export data remains
    // sufficient for conversation-order reply classification when absent.
    let ids = m.meta?.email?.email?.messageIds || m.meta?.email?.messageIds || [];
    // Diagnostic mode reproduces the former invalid fallback without posting.
    // It records only status categories, never IDs, bodies, paths, or headers.
    if (!ids.length && mode === 'diagnose') ids = [m.id];
    if (!ids.length) { detailIdsMissing++; continue; }
    for (const id of ids) {
      try {
        const email = await client.get(`/conversations/messages/email/${encodeURIComponent(id)}`);
        if (email.locationId && email.locationId !== env.GHL_LOCATION_ID) throw new Error('Email location mismatch');
        if (email.direction === 'inbound' && Date.parse(email.dateAdded) >= start && Date.parse(email.dateAdded) <= end) {
          if (ids.length === 1) Object.assign(m, email);
          else emails.push(email);
          enriched++;
        }
      } catch (e) {
        const failure = safeFailure(e, 'email_detail');
        const code = `${failure.category}:${failure.status || 'none'}`;
        detailFailures[code] = (detailFailures[code] || 0) + 1;
      }
    }
  }
  const contacts = await client.contacts();
  const { alerts, unlinked } = prepareBackfill(emails, contacts, env.GHL_LOCATION_ID, start, end);
  const live = await new GithubState(args).load();
  state ||= { version: 1, since: start, until: end, sent: {}, skippedLive: {} };
  if (state.version !== 1 || state.since !== start) throw new Error('Invalid historical checkpoint');
  for (const a of alerts) if (live?.seen?.[a.messageHash]) state.skippedLive[a.key] = true;
  const pending = alerts.filter(a => !state.sent[a.key] && !state.skippedLive[a.key]);
  console.log(JSON.stringify({ mode, enriched, detailIdsMissing, detailFailures, qualifyingReplies: alerts.length, unlinkedInbound: unlinked,
    alreadyPosted: Object.keys(state.sent).length, skippedLive: Object.keys(state.skippedLive).length, pending: pending.length,
    since: new Date(start).toISOString(), until: new Date(end).toISOString() }));
  if (mode !== 'post') return;
  await store.save(state);
  let sent = 0;
  for (const alert of pending.slice(0,300)) {
    const result = await deliver(alert, env.SLACK_BOT_TOKEN);
    if (!result.ok) throw new Error(`Historical Slack delivery failed: ${result.code}; rerun to resume`);
    state.sent[alert.key] = true;
    await store.save(state);
    sent++;
    await new Promise(resolve => setTimeout(resolve, 1100));
  }
  console.log(JSON.stringify({ postedThisRun: sent, postedTotal: Object.keys(state.sent).length, remaining: pending.length - sent }));
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch(error => {
    console.error(JSON.stringify({ event: 'historical_backfill_failed', ...safeFailure(error, 'backfill') }));
    console.error('Historical backfill failed; encrypted checkpoint retained. No secret-bearing error details logged.');
    process.exitCode = 1;
  });
}
