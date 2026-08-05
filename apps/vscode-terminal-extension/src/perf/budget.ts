// Performance NFR budgets and helpers (#1839).
//
// Ships the §17.1 NFR targets as a first-class registry so both the
// runtime harness and the CI perf-check script can consume the same
// source of truth. Hitting the numbers is a separate ticket; this
// module provides the machinery to measure and gate.

export interface PerfBudget {
  metric: string;
  target_ms: number;
  allow_regression_pct: number;
  description: string;
}

export const NFR_BUDGETS: readonly PerfBudget[] = [
  {
    metric: "activation",
    target_ms: 500,
    allow_regression_pct: 10,
    description: "Extension activation time excludes back-end start",
  },
  {
    metric: "webview_first_paint_fixture",
    target_ms: 300,
    allow_regression_pct: 10,
    description: "Webview first-paint fixture mode",
  },
  {
    metric: "webview_first_paint_live",
    target_ms: 1000,
    allow_regression_pct: 10,
    description: "Webview first-paint live API after back-end healthy",
  },
  {
    metric: "symbol_context_propagation",
    target_ms: 100,
    allow_regression_pct: 10,
    description: "Symbol context propagation end-to-end",
  },
  {
    metric: "backend_start",
    target_ms: 30000,
    allow_regression_pct: 10,
    description: "Back-end start time from cold",
  },
  {
    metric: "widget_hot_reload",
    target_ms: 2000,
    allow_regression_pct: 10,
    description: "Widget hot-reload dev mode after source change",
  },
];

export interface BudgetCheckResult {
  pass: boolean;
  budget: PerfBudget | null;
  deltaPct?: number;
  message: string;
}

export function checkBudget(metric: string, actual_ms: number): BudgetCheckResult {
  const budget = NFR_BUDGETS.find((b) => b.metric === metric) ?? null;
  if (!budget) {
    return {
      pass: false,
      budget: null,
      message: `Unknown metric: ${metric}`,
    };
  }
  const ceiling = budget.target_ms * (1 + budget.allow_regression_pct / 100);
  const deltaPct = ((actual_ms - budget.target_ms) / budget.target_ms) * 100;
  if (actual_ms < ceiling) {
    return {
      pass: true,
      budget,
      deltaPct,
      message: `${metric}: ${actual_ms.toFixed(1)}ms <= ceiling ${ceiling.toFixed(
        1,
      )}ms (target ${budget.target_ms}ms, +${budget.allow_regression_pct}%)`,
    };
  }
  return {
    pass: false,
    budget,
    deltaPct,
    message: `${metric}: ${actual_ms.toFixed(1)}ms EXCEEDS ceiling ${ceiling.toFixed(
      1,
    )}ms (target ${budget.target_ms}ms, +${budget.allow_regression_pct}%)`,
  };
}

// Minimal fs surface we depend on so callers (tests) can inject an
// in-memory implementation.
export interface FsPromisesLike {
  readFile(path: string, encoding: BufferEncoding): Promise<string>;
  writeFile(path: string, data: string, encoding: BufferEncoding): Promise<void>;
  mkdir?(path: string, opts: { recursive: boolean }): Promise<unknown>;
}

async function defaultFs(): Promise<FsPromisesLike> {
  const mod = await import("fs");
  return mod.promises as unknown as FsPromisesLike;
}

export async function loadPreviousMeasurements(
  path: string,
  fsPromises?: FsPromisesLike,
): Promise<Record<string, number>> {
  const fs = fsPromises ?? (await defaultFs());
  try {
    const raw = await fs.readFile(path, "utf8");
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object") {
      return parsed as Record<string, number>;
    }
    return {};
  } catch {
    return {};
  }
}

export async function saveMeasurements(
  path: string,
  measurements: Record<string, number>,
  fsPromises?: FsPromisesLike,
): Promise<void> {
  const fs = fsPromises ?? (await defaultFs());
  if (fs.mkdir) {
    try {
      const dir = path.replace(/[/\\][^/\\]+$/, "");
      if (dir && dir !== path) {
        await fs.mkdir(dir, { recursive: true });
      }
    } catch {
      // best effort
    }
  }
  await fs.writeFile(path, JSON.stringify(measurements, null, 2), "utf8");
}
