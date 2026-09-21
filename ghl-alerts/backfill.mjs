import { createHash } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import { GhlClient } from './poll.mjs';
import { GithubState } from './github-state.mjs';
import { normalize, deliver } from './core.mjs';

const digest = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');
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
    const explicitReply = !!m.replyToMessageId;
    if (!explicitReply && !parent) { unlinked++; continue; }
    const alert = normalize({ ...m, type: 'InboundMessage', locationId,
      name: names.get(m.contactId) || m.from || m.contactId || 'Unknown contact',
      messageType: 'Email', webhookId: `message:${m.id}`, timestamp: m.dateAdded });
    alert.title = [...`[Historical] Email reply ? ${names.get(m.contactId) || m.from || m.contactId || 'Unknown contact'}`].slice(0,150).join('');
    alert.description = `Received: ${m.dateAdded}\n${m.subject ? `Subject: ${m.subject}\n` : ''}`
      + (explicitReply ? 'GHL identifies this as an email reply.\n' : 'Inbound email after an earlier outbound email in the same conversation.\n')
      + alert.description;
    alert.description = [...alert.description].slice(0,2800).join('');
    alert.messageHash = digest(m.id);
    alerts.push(alert);
  }
  return { alerts, unlinked };
}

async function main(env = process.env) {
  const mode = env.BACKFILL_MODE || 'inspect';
  if (!['inspect','post'].includes(mode)) throw new Error('Invalid backfill mode');
  const client = new GhlClient(env.GHL_API_TOKEN, env.GHL_LOCATION_ID);
  const args = { repo: env.GITHUB_REPOSITORY, token: env.GITHUB_TOKEN, key: env.ALERT_STATE_KEY, locationId: env.GHL_LOCATION_ID };
  const store = new GithubState({ ...args, namespace: 'email-backfill-2026-06' });
  let state = await store.load();
  const start = Date.parse('2026-06-01T00:00:00+08:00');
  const end = state?.until || Date.now();
  const emails = await client.messages(start, end, ['Email']);
  const inbound = emails.filter(m => m.direction === 'inbound');
  console.log(JSON.stringify({ emails: emails.length, inbound: inbound.length, people: new Set(inbound.map(m => m.contactId)).size,
    directReplyReferences: inbound.filter(m => m.replyToMessageId).length,
    nestedEmailIds: inbound.filter(m => m.meta?.email?.email?.messageIds?.length || m.meta?.email?.messageIds?.length).length,
    bodyAvailable: inbound.filter(m => m.body).length }));
  // Try the email endpoint for reply references, subjects and complete bodies.
  // A missing email object is not evidence of a reply; conversation ordering is
  // the fallback and is described explicitly in the Slack alert.
  let enriched = 0;
  for (const m of inbound) {
    const ids = m.meta?.email?.email?.messageIds || m.meta?.email?.messageIds || [m.id];
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
        if (!String(e.message).endsWith('returned 404')) throw new Error('Email detail lookup failed; no alerts posted');
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
  console.log(JSON.stringify({ mode, enriched, qualifyingReplies: alerts.length, unlinkedInbound: unlinked,
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
  main().catch(() => { console.error('Historical backfill failed; encrypted checkpoint retained. No secret-bearing error details logged.'); process.exitCode = 1; });
}
