// Guided API-key manager (#1836).
//
// Resolves the path to `user_settings.json`, reads/writes it safely
// with a `.bak` backup, and opens it in the editor for the user to
// paste the credential value in. The manager MUST NEVER accept,
// echo, log, or persist the credential value itself — the user
// types it directly into their editor.

import * as os from "node:os";
import * as path from "node:path";
import * as nodeFs from "node:fs/promises";

export const KNOWN_KEYS = [
  "fmp_api_key",
  "fmp_cached_api_key",
  "fred_api_key",
  "polygon_api_key",
  "intrinio_api_key",
  "tiingo_api_key",
] as const;

export type KnownKey = (typeof KNOWN_KEYS)[number];

export interface ApiKeyManagerConfig {
  userSettingsPath?: string;
  fsPromises?: typeof nodeFs;
  homedir?: () => string;
  /**
   * When true (default), successful `writeSettings` calls delete the
   * `.bak` file after the new write completes. Tests may set this to
   * false to inspect the backup content.
   */
  deleteBak?: boolean;
}

export interface ReadSettingsResult {
  path: string;
  content: string;
  parsed?: Record<string, unknown>;
}

export class ApiKeyManager {
  private readonly override?: string;
  private readonly fs: typeof nodeFs;
  private readonly homedir: () => string;
  private readonly deleteBak: boolean;

  constructor(config: ApiKeyManagerConfig = {}) {
    this.override =
      config.userSettingsPath && config.userSettingsPath.length > 0
        ? config.userSettingsPath
        : undefined;
    this.fs = config.fsPromises ?? nodeFs;
    this.homedir = config.homedir ?? os.homedir;
    this.deleteBak = config.deleteBak !== false;
  }

  resolvePath(): string {
    if (this.override) {
      return this.override;
    }
    return path.join(this.homedir(), ".openbb_platform", "user_settings.json");
  }

  async readSettings(): Promise<ReadSettingsResult> {
    const p = this.resolvePath();
    let content: string;
    try {
      content = await this.fs.readFile(p, "utf8");
    } catch {
      return { path: p, content: "", parsed: {} };
    }
    let parsed: Record<string, unknown> = {};
    try {
      const raw = JSON.parse(content) as unknown;
      if (raw && typeof raw === "object" && !Array.isArray(raw)) {
        parsed = raw as Record<string, unknown>;
      }
    } catch {
      parsed = {};
    }
    return { path: p, content, parsed };
  }

  async writeSettings(content: string): Promise<void> {
    const p = this.resolvePath();
    const bakPath = `${p}.bak`;
    let hadPrior = false;
    try {
      await this.fs.access(p);
      await this.fs.rename(p, bakPath);
      hadPrior = true;
      try {
        await this.fs.chmod(bakPath, 0o600);
      } catch (e) {
        console.warn(
          `[apikey] failed to chmod 0600 on ${bakPath}: ${String(e)}`,
        );
      }
    } catch {
      // no existing file — no backup needed
    }
    const dir = path.dirname(p);
    try {
      await this.fs.mkdir(dir, { recursive: true });
    } catch {
      // ignore
    }
    // #1856 — credentials file is user-scope only; enforce 0600.
    await this.fs.writeFile(p, content, { mode: 0o600, encoding: "utf8" });
    try {
      await this.fs.chmod(p, 0o600);
    } catch (e) {
      console.warn(`[apikey] failed to chmod 0600 on ${p}: ${String(e)}`);
    }
    if (hadPrior && this.deleteBak) {
      try {
        await this.fs.unlink(bakPath);
      } catch (e) {
        console.warn(`[apikey] failed to delete ${bakPath}: ${String(e)}`);
      }
    }
  }

  async openInEditor(
    vscodeApi: typeof import("vscode"),
  ): Promise<void> {
    const p = this.resolvePath();
    const uri = vscodeApi.Uri.file(p);
    const doc = await vscodeApi.workspace.openTextDocument(uri);
    await vscodeApi.window.showTextDocument(doc);
  }
}
