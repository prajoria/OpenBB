// Backend auto-restart controller (#1838).
//
// Small, dependency-free state machine that counts restart attempts,
// applies a per-attempt backoff, and calls user-supplied onRetry /
// onGiveUp hooks. Sleep is injectable so tests can run without wall
// clock delays.

export interface RestartControllerConfig {
  maxAttempts: number;
  backoffMs: number[];
  onRetry: (attempt: number) => Promise<void>;
  onGiveUp: () => void;
  log?: (msg: string) => void;
  sleep?: (ms: number) => Promise<void>;
}

export class RestartController {
  private attempts = 0;
  constructor(private cfg: RestartControllerConfig) {}
  get attemptCount(): number {
    return this.attempts;
  }
  reset(): void {
    this.attempts = 0;
  }
  async attemptRestart(): Promise<void> {
    if (this.attempts >= this.cfg.maxAttempts) {
      this.cfg.onGiveUp();
      return;
    }
    const idx = this.attempts;
    const delay =
      this.cfg.backoffMs[Math.min(idx, this.cfg.backoffMs.length - 1)];
    this.attempts += 1;
    this.cfg.log?.(
      `[auto-restart] attempt ${this.attempts}/${this.cfg.maxAttempts}...`,
    );
    const sleep =
      this.cfg.sleep ?? ((ms: number) => new Promise((r) => setTimeout(r, ms)));
    await sleep(delay);
    await this.cfg.onRetry(this.attempts);
  }
}
