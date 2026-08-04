// Runtime performance harness (#1839).
//
// Wraps a tiny mark/measure API around an injectable time source so the
// same code paths can be exercised deterministically from node:test.

import {
  NFR_BUDGETS,
  checkBudget,
  saveMeasurements,
  BudgetCheckResult,
  FsPromisesLike,
} from "./budget";

export type TimeSource = () => number;

export interface PerfHarnessOptions {
  reportPath?: string;
  timeSource?: TimeSource;
  fsPromises?: FsPromisesLike;
}

export class PerfHarness {
  private readonly marks = new Map<string, number>();
  private readonly measurements: Record<string, number> = {};
  private readonly reportPath: string | undefined;
  private readonly now: TimeSource;
  private readonly fs: FsPromisesLike | undefined;

  constructor(opts: PerfHarnessOptions = {}) {
    this.reportPath = opts.reportPath;
    this.now = opts.timeSource ?? (() => Date.now());
    this.fs = opts.fsPromises;
  }

  mark(label: string): void {
    this.marks.set(label, this.now());
  }

  measure(label: string): number {
    const start = this.marks.get(label);
    if (start === undefined) {
      throw new Error(`PerfHarness.measure(${label}): no matching mark()`);
    }
    const elapsed = this.now() - start;
    this.measurements[label] = elapsed;
    return elapsed;
  }

  record(label: string, ms: number): void {
    this.measurements[label] = ms;
  }

  report(): Record<string, number> {
    return { ...this.measurements };
  }

  async persist(): Promise<void> {
    if (!this.reportPath) {
      return;
    }
    await saveMeasurements(this.reportPath, this.report(), this.fs);
  }

  async checkAll(): Promise<BudgetCheckResult[]> {
    const results: BudgetCheckResult[] = [];
    for (const budget of NFR_BUDGETS) {
      const actual = this.measurements[budget.metric];
      if (actual === undefined) {
        results.push({
          pass: true,
          budget,
          message: `${budget.metric}: not measured (skipped)`,
        });
        continue;
      }
      results.push(checkBudget(budget.metric, actual));
    }
    return results;
  }
}
