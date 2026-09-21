import { GhlClient } from './poll.mjs';

const client = new GhlClient(process.env.GHL_API_TOKEN, process.env.GHL_LOCATION_ID);
const start = Date.parse('2026-06-01T00:00:00+08:00');
const end = Date.now();
const emails = await client.messages(start, end, ['Email']);
const inbound = emails.filter(m => m.direction === 'inbound');
console.log(JSON.stringify({ emails: emails.length, inbound: inbound.length,
  people: new Set(inbound.map(m => m.contactId)).size,
  months: Object.fromEntries([...new Set(inbound.map(m => m.dateAdded.slice(0,7)))].map(month => [month, inbound.filter(m => m.dateAdded.startsWith(month)).length])),
  directReplyReferences: inbound.filter(m => m.replyToMessageId).length,
  nestedEmailIds: inbound.filter(m => m.meta?.email?.email?.messageIds?.length || m.meta?.email?.messageIds?.length).length,
  bodyAvailable: inbound.filter(m => m.body).length,
  exampleFieldNames: inbound[0] ? Object.keys(inbound[0]) : [],
}));
