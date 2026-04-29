import * as vscode from "vscode";
import { NotesViewProvider } from "./notesProvider";

export function activate(context: vscode.ExtensionContext): void {
  const provider = new NotesViewProvider(context);

  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(NotesViewProvider.viewType, provider, {
      webviewOptions: { retainContextWhenHidden: true },
    }),
    vscode.commands.registerCommand("sidebarNotes.refresh", () => provider.reloadFromDisk()),
    vscode.commands.registerCommand("sidebarNotes.openFile", () => provider.openInEditor()),
  );
}

export function deactivate(): void {
  // nothing to clean up; provider disposes via context.subscriptions
}
