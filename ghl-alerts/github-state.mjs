import { createCipheriv, createDecipheriv, randomBytes } from 'node:crypto';
import { gzipSync, gunzipSync } from 'node:zlib';

export function encryptState(state, secret, context) {
  const key = Buffer.from(secret, 'base64');
  if (key.length !== 32) throw new Error('ALERT_STATE_KEY must be 32 random bytes encoded as base64');
  const iv = randomBytes(12);
  const cipher = createCipheriv('aes-256-gcm', key, iv);
  cipher.setAAD(Buffer.from(context));
  const data = Buffer.concat([cipher.update(gzipSync(JSON.stringify(state))), cipher.final()]);
  return JSON.stringify({ version: 1, iv: iv.toString('base64'), tag: cipher.getAuthTag().toString('base64'), data: data.toString('base64') });
}

export function decryptState(value, secret, context) {
  const packed = JSON.parse(value);
  if (packed.version !== 1) throw new Error('Unsupported checkpoint version');
  const cipher = createDecipheriv('aes-256-gcm', Buffer.from(secret, 'base64'), Buffer.from(packed.iv, 'base64'));
  cipher.setAAD(Buffer.from(context));
  cipher.setAuthTag(Buffer.from(packed.tag, 'base64'));
  const plain = Buffer.concat([cipher.update(Buffer.from(packed.data, 'base64')), cipher.final()]);
  return JSON.parse(gunzipSync(plain, { maxOutputLength: 50_000_000 }).toString('utf8'));
}

// Durable encrypted state on a dedicated branch, never on the code branch.
export class GithubState {
  constructor({ repo, token, key, locationId, namespace, fetcher = fetch }) {
    if (!/^[\w.-]+\/[\w.-]+$/.test(repo || '')) throw new Error('Invalid repository');
    this.repo = repo; this.token = token; this.key = key; this.fetcher = fetcher;
    this.context = `${repo}:${locationId}:ghl-alerts-v1`;
    this.branch = 'ghl-alert-state'; this.path = 'checkpoint.enc.json'; this.sha = null;
    if (namespace) {
      if (!/^[a-z0-9-]+$/.test(namespace)) throw new Error('Invalid checkpoint namespace');
      this.path = `${namespace}.enc.json`; this.context += `:${namespace}`;
      this.allowNewFile = true;
    }
  }
  async request(path, method = 'GET', body) {
    const response = await this.fetcher(`https://api.github.com/repos/${this.repo}${path}`, {
      method, redirect: 'error', signal: AbortSignal.timeout(30_000),
      headers: { Authorization: `Bearer ${this.token}`, Accept: 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28', 'Content-Type': 'application/json' },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    if (response.status === 404) return null;
    if (!response.ok) throw new Error(`GitHub state API returned ${response.status}`);
    return response.json();
  }
  async load() {
    const branch = await this.request(`/git/ref/heads/${this.branch}`);
    this.exists = !!branch;
    if (!branch) return null;
    const file = await this.request(`/contents/${this.path}?ref=${this.branch}`);
    if (!file && this.allowNewFile) return null;
    if (!file?.content || !file.sha) throw new Error('Checkpoint missing on state branch; refusing to reset the baseline');
    this.sha = file.sha;
    return decryptState(Buffer.from(file.content, 'base64').toString('utf8'), this.key, this.context);
  }
  async save(state) {
    const value = encryptState(state, this.key, this.context);
    if (Buffer.byteLength(value) > 900_000) throw new Error('Encrypted checkpoint exceeds safe GitHub Contents API limit');
    if (!this.exists) {
      const repository = await this.request('');
      const head = await this.request(`/git/ref/heads/${repository.default_branch}`);
      await this.request('/git/refs', 'POST', { ref: `refs/heads/${this.branch}`, sha: head.object.sha });
      this.exists = true;
    }
    const file = await this.request(`/contents/${this.path}`, 'PUT', {
      message: 'Save encrypted GHL alert checkpoint [skip ci]', branch: this.branch,
      content: Buffer.from(value).toString('base64'), ...(this.sha ? { sha: this.sha } : {}),
    });
    if (!file?.content?.sha) throw new Error('Checkpoint save was not confirmed');
    this.sha = file.content.sha;
  }
}
