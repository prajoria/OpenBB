// Editor selection ticker CodeAction (#1827).
//
// PRD §13.1: selecting text that matches a ticker pattern is the LOWEST
// -priority symbol source. It MUST NOT auto-broadcast; instead we offer
// a lightbulb CodeAction the user must explicitly accept.

import * as vscode from "vscode";

const TICKER_RE = /^[A-Z]{1,5}(:[A-Z]+)?$/;

/**
 * Pure helper — matches the trimmed selected text against the ticker
 * pattern. Returns the normalized symbol or `undefined`.
 */
export function matchTicker(raw: string): string | undefined {
  const s = (raw ?? "").trim();
  if (!s) return undefined;
  return TICKER_RE.test(s) ? s : undefined;
}

export class TickerSelectionActionProvider
  implements vscode.CodeActionProvider
{
  provideCodeActions(
    document: vscode.TextDocument,
    range: vscode.Range | vscode.Selection,
    ctx: vscode.CodeActionContext,
    _token: vscode.CancellationToken,
  ): vscode.CodeAction[] | undefined {
    // Only fire on explicit user invocation — never auto-suggest.
    if (ctx.triggerKind !== vscode.CodeActionTriggerKind.Invoke) {
      return undefined;
    }
    const sym = matchTicker(document.getText(range));
    if (!sym) return undefined;
    const action = new vscode.CodeAction(
      `Open ${sym} in OpenBB Terminal`,
      vscode.CodeActionKind.RefactorRewrite,
    );
    action.command = {
      command: "openbb.openSymbolInTerminal",
      title: "Open in OpenBB Terminal",
      arguments: [sym],
    };
    return [action];
  }
}

export function registerSelectionCodeAction(
  context: vscode.ExtensionContext,
): vscode.Disposable {
  const provider = new TickerSelectionActionProvider();
  const disposable = vscode.languages.registerCodeActionsProvider(
    ["python", "markdown", "plaintext", "typescript", "javascript"],
    provider,
    {
      providedCodeActionKinds: [vscode.CodeActionKind.RefactorRewrite],
    },
  );
  context.subscriptions.push(disposable);
  return disposable;
}
