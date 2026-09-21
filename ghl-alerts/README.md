# GHL activity alerts in GitHub Actions

Checks GHL every five minutes and posts new activity to Slack channel `C0BQK1SQ2RM`. Manual runs are available under **Actions → GHL activity alerts → Run workflow**. No Vercel deployment, external database or GHL workflow is required.

## Configuration

Repository secrets:

- `GHL_SECRET_KEY` and `GHL_LOCATION_ID`: existing GHL credentials.
- `SLACK_BOT_TOKEN`: Slack bot token with `chat:write`; invite this bot to the target channel.
- `ALERT_STATE_KEY`: 32 cryptographically random bytes, base64 encoded. Keep this key stable; changing it requires an explicit checkpoint migration/reset.

Repository variable `GHL_ALERTS_ENABLED=true` enables scheduled runs. Leave it unset until verification succeeds. GitHub schedules are best-effort, may run late, and require the workflow on the default branch. Manual runs work regardless of this variable. Disable the variable to pause scheduling.

Modes:

- `dry-run`: reads GHL and reports counts, without sending messages or changing state.
- `test-slack`: sends one explicitly labeled delivery test. Does not enable monitoring.
- `poll`: first successful run saves a baseline without historical alerts; later runs capture and send new activity.

## Coverage

- Inbound and outbound conversation messages, including an explicit email export.
- Other activity entries returned by GHL's message export.
- New contacts and changes to selected contact fields, including tags, DND and owner.
- New opportunities and changes to stage, pipeline, status, owner, value and custom fields.

This is polling, not a complete event audit. Deleted records and intermediate changes between checks are not reliably detected. Reverted changes between two scans can be missed. Group Chat and SMS Review Request types are excluded by GHL's export endpoint. Notes/tasks/appointments only appear if exposed as message-export activity; there is no independent complete scan for these categories. Inbound email is not asserted to be a reply to an automated campaign without source correlation. IDs appear where names are unavailable. No previous value or actor is invented.

The implementation uses the date-versioned contacts and opportunity listing APIs already used by this repository. Those endpoints are marked deprecated in GHL documentation; a future removal will cause visible workflow failures rather than silently advancing the checkpoint. Each collection is fully paginated with a 50,000-record ceiling. Duplicate pagination records fail the run so an incomplete snapshot is not accepted.

## State and delivery

This repository is public. Contact snapshots and pending message bodies are gzip-compressed and encrypted using AES-256-GCM before being stored as `checkpoint.enc.json` on the `ghl-alert-state` branch. The encryption context binds the file to the repository and location. Credentials and plaintext customer data are never committed or logged. The key lives only in GitHub Secrets. State commits do not touch the code branch.

Each complete scan saves its snapshot and pending outbox before sending. Each acknowledged Slack send removes that item and saves again. Failed alerts remain encrypted for the next run. A maximum of 100 alerts is sent per batch, paced at about one per second. Existing pending alerts are retried before collecting more. A Slack error fails the run, leaving the outbox intact. GitHub concurrency prevents simultaneous polling runs.

Messages are rescanned with a 24-hour overlap to tolerate delayed indexing; IDs are retained for seven days to suppress duplicate alerts. After downtime, the window starts from the previous successful checkpoint, not simply the most recent five minutes. First-run historical messages are intentionally suppressed.

Delivery is at least once: a lost Slack response or checkpoint-write failure after a successful send can produce a duplicate on retry. Changes represented both in snapshots and GHL activity messages may produce separate alerts. Historical ciphertext remains in Git history; protect the encryption key. Checkpoints larger than 900 KB fail before sending because the GitHub Contents API is used for state. For large accounts, a dedicated durable store is preferable.

The service does not accept public incoming webhooks and requires no Slack CLI or support-agent template. The supplied Slack app manifest requests only `chat:write`.

## Verification

## Historical email backfill

The manual **GHL historical email replies** workflow currently posts concise email replies from August 1, 2026
(Asia/Singapore midnight). `inspect` reports counts without posting; `post` sends
up to 300 historical reply alerts per run and can be rerun to resume. The first
posting run fixes the end timestamp in a separate encrypted checkpoint. It does
not rewind the live polling baseline. Previously queued live messages are skipped.

Alerts use an explicit reply reference when available, or describe an inbound
email following an earlier outbound email in the same conversation. Inbound
emails without either link are counted but not posted as proven replies. The
backfill does not assert that every original email was automated. Sent IDs are
stored separately; a lost Slack response/checkpoint failure still has the same
at-least-once delivery limitation as live polling.

## Verification

Node 24, no runtime dependencies:

```sh
cd ghl-alerts
npm test
```

Tests cover baseline suppression, change detection, repeat-message suppression, encrypted-state integrity, partial Slack failures, pagination and safe formatting. Live activation requires the `test-slack` and `dry-run` workflow modes to succeed, followed by a baseline `poll` and enabling the schedule variable.

## References

- GHL message export: https://marketplace.gohighlevel.com/docs/2021-07-28/ghl/conversations/export-messages-by-location/
- GHL contacts: https://marketplace.gohighlevel.com/docs/2021-07-28/ghl/contacts/get-contacts/
- GHL opportunities: https://marketplace.gohighlevel.com/docs/2021-07-28/ghl/opportunities/search-opportunity/
- GitHub scheduling: https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule

## Automatic contact email updates

During each live poll, an inbound email can update its matching GHL contact when the message clearly refers to a new or changed email address and contains exactly one replacement address. The automation skips ambiguous messages and addresses already owned by another contact. It records a successful update in the same Slack reply alert. A failed GHL update stops the poll before its checkpoint advances, so the next run safely retries it.
