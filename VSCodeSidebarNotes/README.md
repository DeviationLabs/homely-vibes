# Sidebar Notes

A markdown sidebar for VS Code and Cursor. Reads from a markdown file in your workspace, persists across restarts, and is writable by Claude (or any other tool) — open the same file in your terminal session and Claude can drop a session summary that shows up live in the sidebar.

Successor to the original Sidebar Notes extension. Fixes typos, adds persistence to disk, and adds two-way sync with an external markdown file.

## Features

- **Persistent**: notes live in `sidebar-notes.md` at your workspace root. Survives reloads, branch switches, and reopens.
- **Live reload**: external edits (e.g. from Claude, `git pull`, another editor) refresh the sidebar immediately.
- **Two-way edit**: toggle preview/edit; edits in the sidebar debounce-save to the file.
- **Workspace-aware**: each workspace gets its own notes file. Falls back to a configurable global file when no workspace is open.
- **Theme-aware**: matches your VS Code theme.

## Usage

1. Click the **Sidebar Notes** icon in the activity bar.
2. The view shows `sidebar-notes.md` from your workspace root, creating it on first edit.
3. Use the toolbar to toggle edit/preview, refresh, or open the file in a regular editor tab.
4. Have Claude write to the file directly:
   ```
   Append a one-paragraph summary of where this session is at to sidebar-notes.md.
   ```
   The sidebar updates as Claude saves.

## Settings

| Setting | Default | Description |
| --- | --- | --- |
| `sidebarNotes.fileName` | `sidebar-notes.md` | Workspace-relative path of the markdown file. |
| `sidebarNotes.globalFile` | _(empty)_ | Absolute path used when no workspace is open. Leave blank to disable. |
| `sidebarNotes.debounceMs` | `400` | Delay between keystroke and save. |

## Development

```bash
cd VSCodeSidebarNotes
npm install
npm run compile        # one-shot bundle to dist/extension.js
npm run watch          # rebuild on save
```

Press `F5` from this folder to launch a VS Code Extension Development Host with the extension loaded.

### Packaging a `.vsix`

```bash
npm run package          # production bundle
npm run package-vsix     # produces vscode-sidebar-notes-<version>.vsix
```

Install the `.vsix` locally with:

```bash
code --install-extension vscode-sidebar-notes-0.0.1.vsix
# or in Cursor:
cursor --install-extension vscode-sidebar-notes-0.0.1.vsix
```

### Publishing to the Marketplace

1. Create a publisher at <https://marketplace.visualstudio.com/manage>.
2. Generate a Personal Access Token with **Marketplace > Manage** scope from <https://dev.azure.com>.
3. Update the `publisher` field in `package.json` if the Deviation Labs publisher name differs.
4. Login once: `npx vsce login deviationlabs`
5. Publish: `npm run publish`

The same `.vsix` works in Cursor (Cursor reads the VS Code marketplace via OpenVSX mirror — list there separately if needed).

## License

MIT — see [LICENSE](LICENSE).
