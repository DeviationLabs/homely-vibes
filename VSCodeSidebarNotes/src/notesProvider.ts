import * as vscode from "vscode";
import * as fs from "fs/promises";
import * as path from "path";

interface InboundMessage {
  type: "save" | "ready" | "openFile";
  text?: string;
}

export class NotesViewProvider implements vscode.WebviewViewProvider {
  public static readonly viewType = "sidebarNotes.view";

  private view?: vscode.WebviewView;
  private watcher?: vscode.FileSystemWatcher;
  private writingOurselves = false;
  private debounceTimer?: NodeJS.Timeout;

  constructor(private readonly context: vscode.ExtensionContext) {
    context.subscriptions.push(
      vscode.workspace.onDidChangeConfiguration((e) => {
        if (e.affectsConfiguration("sidebarNotes")) {
          this.rewatch();
          void this.reloadFromDisk();
        }
      }),
      vscode.workspace.onDidChangeWorkspaceFolders(() => {
        this.rewatch();
        void this.reloadFromDisk();
      }),
    );
  }

  public resolveWebviewView(view: vscode.WebviewView): void {
    this.view = view;
    view.webview.options = {
      enableScripts: true,
      localResourceRoots: [vscode.Uri.joinPath(this.context.extensionUri, "media")],
    };
    view.webview.html = this.renderHtml(view.webview);

    view.webview.onDidReceiveMessage((m: InboundMessage) => this.handleMessage(m));
    view.onDidDispose(() => {
      this.view = undefined;
      this.watcher?.dispose();
      this.watcher = undefined;
    });

    this.rewatch();
  }

  public async reloadFromDisk(): Promise<void> {
    if (!this.view) return;
    const filePath = this.resolveFilePath();
    if (!filePath) {
      this.postState({ text: "", filePath: "", missing: true });
      return;
    }
    const text = await this.readOrEmpty(filePath);
    this.postState({ text, filePath, missing: false });
  }

  public async openInEditor(): Promise<void> {
    const filePath = this.resolveFilePath();
    if (!filePath) {
      vscode.window.showWarningMessage("Sidebar Notes: no workspace folder and no global file configured.");
      return;
    }
    await this.ensureFileExists(filePath);
    const doc = await vscode.workspace.openTextDocument(filePath);
    await vscode.window.showTextDocument(doc);
  }

  private handleMessage(m: InboundMessage): void {
    if (m.type === "ready") {
      void this.reloadFromDisk();
      return;
    }
    if (m.type === "openFile") {
      void this.openInEditor();
      return;
    }
    if (m.type === "save" && typeof m.text === "string") {
      this.scheduleSave(m.text);
    }
  }

  private scheduleSave(text: string): void {
    const cfg = vscode.workspace.getConfiguration("sidebarNotes");
    const delay = cfg.get<number>("debounceMs", 0);
    if (this.debounceTimer) clearTimeout(this.debounceTimer);
    this.debounceTimer = setTimeout(() => void this.writeToDisk(text), delay);
  }

  private async writeToDisk(text: string): Promise<void> {
    const filePath = this.resolveFilePath();
    if (!filePath) return;
    try {
      await fs.mkdir(path.dirname(filePath), { recursive: true });
      this.writingOurselves = true;
      await fs.writeFile(filePath, text, "utf8");
    } catch (err) {
      vscode.window.showErrorMessage(`Sidebar Notes: failed to save: ${err}`);
    } finally {
      setTimeout(() => {
        this.writingOurselves = false;
      }, 200);
    }
  }

  private rewatch(): void {
    this.watcher?.dispose();
    this.watcher = undefined;
    const filePath = this.resolveFilePath();
    if (!filePath) return;
    const folder = vscode.workspace.workspaceFolders?.[0];
    if (folder && filePath.startsWith(folder.uri.fsPath)) {
      const rel = path.relative(folder.uri.fsPath, filePath);
      this.watcher = vscode.workspace.createFileSystemWatcher(
        new vscode.RelativePattern(folder, rel),
      );
    } else {
      this.watcher = vscode.workspace.createFileSystemWatcher(filePath);
    }
    const onChange = () => {
      if (this.writingOurselves) return;
      void this.reloadFromDisk();
    };
    this.watcher.onDidChange(onChange);
    this.watcher.onDidCreate(onChange);
    this.watcher.onDidDelete(onChange);
    this.context.subscriptions.push(this.watcher);
  }

  private resolveFilePath(): string | undefined {
    const cfg = vscode.workspace.getConfiguration("sidebarNotes");
    const fileName = cfg.get<string>("fileName", "sidebar-notes.md");
    const globalFile = cfg.get<string>("globalFile", "");
    const folder = vscode.workspace.workspaceFolders?.[0];
    if (folder) return path.join(folder.uri.fsPath, fileName);
    if (globalFile) return globalFile;
    return undefined;
  }

  private async readOrEmpty(filePath: string): Promise<string> {
    try {
      return await fs.readFile(filePath, "utf8");
    } catch {
      return "";
    }
  }

  private async ensureFileExists(filePath: string): Promise<void> {
    try {
      await fs.access(filePath);
    } catch {
      await fs.mkdir(path.dirname(filePath), { recursive: true });
      await fs.writeFile(filePath, "# Notes\n\nWrite anything here. Claude can edit this file too.\n", "utf8");
    }
  }

  private postState(state: { text: string; filePath: string; missing: boolean }): void {
    this.view?.webview.postMessage({ type: "state", ...state });
  }

  private renderHtml(webview: vscode.Webview): string {
    const nonce = makeNonce();
    const csp = [
      `default-src 'none'`,
      `style-src ${webview.cspSource} 'unsafe-inline'`,
      `script-src 'nonce-${nonce}'`,
      `img-src ${webview.cspSource} https: data:`,
      `font-src ${webview.cspSource}`,
    ].join("; ");

    const mediaUri = (file: string) =>
      webview.asWebviewUri(vscode.Uri.joinPath(this.context.extensionUri, "media", file));

    return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta http-equiv="Content-Security-Policy" content="${csp}" />
  <link rel="stylesheet" href="${mediaUri("main.css")}" />
</head>
<body>
  <div id="status"></div>
  <textarea id="editor" spellcheck="false"></textarea>
  <script nonce="${nonce}" src="${mediaUri("main.js")}"></script>
</body>
</html>`;
  }
}

function makeNonce(): string {
  const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  let out = "";
  for (let i = 0; i < 32; i++) out += chars.charAt(Math.floor(Math.random() * chars.length));
  return out;
}
