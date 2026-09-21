import { createHash, createPublicKey, verify } from 'node:crypto';

// Official GHL Ed25519 public key, not a credential.
export const GHL_PUBLIC_KEY = `-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAi2HR1srL4o18O8BRa7gVJY7G7bupbN3H9AwJrHCDiOg=
-----END PUBLIC KEY-----`;
export const CHANNEL = 'C0BQK1SQ2RM';
const string = (v) => typeof v === 'string' ? v.trim() : '';
const clip = (s, n) => [...s].length > n ? [...s].slice(0, n - 1).join('') + '…' : s;
const words = (s) => s.replace(/([a-z])([A-Z])/g, '$1 $2');
const object = (v) => v && typeof v === 'object' && !Array.isArray(v);
export function cleanMessage(value, limit = 420) {
  let text = string(value);
  if (!text) return '';
  text = text.replace(/<blockquote\b[\s\S]*$/i, '')
    .replace(/<(script|style)\b[^>]*>[\s\S]*?<\/\1>/gi, ' ')
    .replace(/<br\s*\/?\s*>|<\/p\s*>|<\/div\s*>/gi, '\n')
    .replace(/<[^>]*>/g, ' ')
    .replace(/&nbsp;/gi, ' ').replace(/&amp;/gi, '&').replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>').replace(/&quot;/gi, '"').replace(/&#39;/gi, "'")
    .replace(/\r/g, '').replace(/[ \t]+/g, ' ').replace(/\n\s*\n+/g, '\n').trim();
  return clip(text, limit);
}

export function validSignature(raw, signature, key = GHL_PUBLIC_KEY) {
  try {
    if (!signature || !/^[A-Za-z0-9+/]+={0,2}$/.test(signature)) return false;
    return verify(null, raw, createPublicKey(key), Buffer.from(signature, 'base64'));
  } catch { return false; }
}

export function normalize(event) {
  if (!object(event)) throw new Error('Expected an event object');
  const data = object(event.data) ? event.data : event;
  const type = string(event.type);
  const locationId = string(event.locationId) || string(data.locationId);
  if (!/^[A-Za-z][A-Za-z0-9]{0,99}$/.test(type) || !locationId) {
    throw new Error('Missing event type or locationId');
  }
  if (event.locationId && data.locationId && event.locationId !== data.locationId) {
    throw new Error('Conflicting locations');
  }
  const name = string(data.name) || string(data.contactName)
    || [string(data.firstName), string(data.lastName)].filter(Boolean).join(' ')
    || string(data.contactId) || string(data.id) || 'GHL record';
  let title = ({ ContactCreate: 'Contact created', ContactDelete: 'Contact deleted',
    ContactTagUpdate: 'Contact tags updated', ContactDndUpdate: 'Communication preferences updated',
    OpportunityCreate: 'Opportunity created', OpportunityDelete: 'Opportunity deleted',
    OpportunityUpdate: 'Opportunity updated', OpportunityAssignedToUpdate: 'Opportunity owner changed',
    NoteCreate: 'Note added', NoteUpdate: 'Note updated', NoteDelete: 'Note deleted',
    TaskCreate: 'Task created', TaskComplete: 'Task completed', TaskDelete: 'Task deleted',
    AppointmentCreate: 'Appointment created', AppointmentUpdate: 'Appointment updated',
    AppointmentDelete: 'Appointment deleted' })[type] || words(type);
  let description = `${title} event received for ${name}.`;
  if (type === 'InboundMessage' || type === 'OutboundMessage') {
    const channel = string(data.messageType) || string(data.messageTypeString) || 'conversation';
    const inboundEmail = type === 'InboundMessage' && channel.toLowerCase() === 'email';
    title = inboundEmail ? 'Email reply' : type === 'InboundMessage' ? `New ${channel} message` : `${channel} message sent`;
    description = inboundEmail && string(data.subject) ? `Subject: ${cleanMessage(data.subject, 140)}` : '';
    if (string(data.body)) {
      description += `${description ? '\n' : ''}${cleanMessage(data.body)}`;
    } else description += `${description ? '\n' : ''}No message preview available.`;
  } else if (type === 'OpportunityStageUpdate') {
    title = 'Pipeline stage changed';
    description = `${name} moved to stage ${string(data.pipelineStageName) || string(data.pipelineStageId) || '(not supplied)'}`
      + ` in pipeline ${string(data.pipelineName) || string(data.pipelineId) || '(not supplied)'}.`;
  } else if (type === 'OpportunityStatusUpdate') {
    title = 'Opportunity status changed';
    description = `${name} now has status ${string(data.status) || '(not supplied)'}.`;
  } else if (type === 'OpportunityMonetaryValueUpdate') {
    title = 'Opportunity value changed';
    description = `${name}: new value ${typeof data.monetaryValue === 'number' ? data.monetaryValue : '(not supplied)'}.`;
  } else if (type === 'ContactUpdate') {
    title = 'Contact updated';
    description = `${name}'s contact information was updated. Review the contact in GHL for details.`;
  }
  // webhookId identifies delivery; record IDs must never deduplicate all future changes.
  // Without webhookId, hash the full event (including timestamps). Identical events
  // without unique IDs/timestamps cannot be distinguished; document this limitation.
  const identity = string(event.webhookId) || createHash('sha256').update(canonical(event)).digest('hex');
  return {
    key: createHash('sha256').update(`${locationId}:${type}:${identity}`).digest('hex'),
    type, locationId,
    title: clip(`${title} — ${name}`, 150), description: clip(description, 2800),
    // dateAdded may be the record creation date, not this event's occurrence time.
    occurredAt: string(event.timestamp) || string(data.dateUpdated) || '',
  };
}

function canonical(value) {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (object(value)) return '{' + Object.keys(value).sort().map(k => JSON.stringify(k) + ':' + canonical(value[k])).join(',') + '}';
  return JSON.stringify(value);
}

export function slackMessage(alert) {
  const date = alert.occurredAt && Number.isFinite(Date.parse(alert.occurredAt))
    ? new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Singapore' }).format(new Date(alert.occurredAt))
    : '';
  const context = `GHL${alert.type === 'HistoricalEmailReply' ? ' historical' : ''}${date ? ` • ${date} SGT` : ''}`;
  return {
    channel: CHANNEL,
    text: `${alert.title}\n${alert.description}\n${context}`.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;'),
    mrkdwn: false, parse: 'none', link_names: false,
    unfurl_links: false, unfurl_media: false,
    blocks: [
      { type: 'header', text: { type: 'plain_text', text: alert.title, emoji: false } },
      { type: 'section', text: { type: 'plain_text', text: alert.description, emoji: false } },
      { type: 'context', elements: [{ type: 'plain_text', text: context, emoji: false }] },
    ],
  };
}

export async function deliver(alert, token, fetcher = fetch) {
  try {
    const response = await fetcher('https://slack.com/api/chat.postMessage', {
      method: 'POST', redirect: 'error', signal: AbortSignal.timeout(15_000),
      headers: { authorization: `Bearer ${token}`, 'content-type': 'application/json' },
      body: JSON.stringify(slackMessage(alert)),
    });
    if (response.status === 429) {
      const seconds = Number(response.headers.get('retry-after'));
      return { ok: false, code: 'rate_limited', retryMs: Number.isFinite(seconds) && seconds > 0 ? seconds * 1000 : 60_000 };
    }
    if (response.status >= 500) return { ok: false, code: 'slack_unavailable' };
    if (!response.ok) return { ok: false, permanent: true, code: `slack_http_${response.status}` };
    const body = await response.json();
    if (body.ok === true) return { ok: true };
    const transient = ['internal_error', 'fatal_error', 'service_unavailable', 'ratelimited'].includes(body.error);
    // Never log arbitrary provider response bodies or credentials.
    const code = /^[a-z_]{1,60}$/.test(body.error) ? body.error : 'slack_rejected';
    return { ok: false, permanent: !transient, code, ...(body.error === 'ratelimited' ? { retryMs: 60_000 } : {}) };
  } catch { return { ok: false, code: 'network_or_response_error' }; }
}

export async function processOne(queue, token, fetcher = fetch) {
  const row = await queue.claim();
  if (!row) return false;
  const result = await deliver(JSON.parse(row.payload), token, fetcher);
  await queue.finish(row, result);
  console.log(JSON.stringify({ event: row.id, delivery: result.ok ? 'sent' : result.code }));
  return true;
}
