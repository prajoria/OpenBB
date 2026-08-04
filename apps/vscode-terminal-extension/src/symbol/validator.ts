// Symbol validator (#1823) — syntax + remote validation with TTL cache
// and in-flight coalescing. No Authorization header, no query-string
// bearer tokens — the local API bridge is unauthenticated per ADR
// 2026-08-04.

export type ValidateResult =
  | { accepted: true }
  | { accepted: false; reason: string };

interface CacheEntry {
  result: ValidateResult;
  expiresAt: number;
}

interface ValidatorOptions {
  apiBase: string;
  ttlMs?: number;
  debounceMs?: number;
  fetchImpl?: typeof fetch;
}

const SYNTAX = /^[A-Z]{1,5}(:[A-Z]+)?$/;

export class SymbolValidator {
  private readonly apiBase: string;
  private readonly ttlMs: number;
  private readonly debounceMs: number;
  private readonly fetchImpl: typeof fetch;
  private readonly cache = new Map<string, CacheEntry>();
  private readonly inflight = new Map<string, Promise<ValidateResult>>();

  constructor(opts: ValidatorOptions) {
    this.apiBase = opts.apiBase.replace(/\/+$/, "");
    this.ttlMs = opts.ttlMs ?? 5 * 60 * 1000;
    this.debounceMs = opts.debounceMs ?? 300;
    this.fetchImpl = opts.fetchImpl ?? fetch;
  }

  async validate(symbol: string): Promise<ValidateResult> {
    if (!SYNTAX.test(symbol)) {
      return { accepted: false, reason: "invalid syntax" };
    }
    const now = Date.now();
    const cached = this.cache.get(symbol);
    if (cached && cached.expiresAt > now) {
      return cached.result;
    }
    const existing = this.inflight.get(symbol);
    if (existing) {
      return existing;
    }
    const promise = this.doFetch(symbol);
    this.inflight.set(symbol, promise);
    try {
      return await promise;
    } finally {
      this.inflight.delete(symbol);
    }
  }

  private async doFetch(symbol: string): Promise<ValidateResult> {
    if (this.debounceMs > 0) {
      await new Promise((r) => setTimeout(r, this.debounceMs));
    }
    const url =
      this.apiBase +
      "/api/v1/equity/search?query=" +
      encodeURIComponent(symbol) +
      "&limit=1";
    let result: ValidateResult;
    let cacheable = true;
    try {
      const resp = await this.fetchImpl(url);
      if (resp.status !== 200) {
        result = { accepted: false, reason: "validator unreachable" };
        cacheable = false;
      } else {
        const body = (await resp.json()) as {
          results?: unknown[];
        } & Record<string, unknown>;
        const arr = Array.isArray(body.results)
          ? body.results
          : Array.isArray((body as { data?: unknown[] }).data)
            ? (body as { data: unknown[] }).data
            : [];
        if (arr.length > 0) {
          result = { accepted: true };
        } else {
          result = { accepted: false, reason: "no matches" };
        }
      }
    } catch {
      result = { accepted: false, reason: "validator unreachable" };
      cacheable = false;
    }
    if (cacheable) {
      this.cache.set(symbol, {
        result,
        expiresAt: Date.now() + this.ttlMs,
      });
    }
    return result;
  }
}
