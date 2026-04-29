# Sticky Sidebar Notes

A always-editable markdown notepad sidebar for VS Code and Cursor. Notes live in a plain text file in your workspace, persist across restarts, and update live when Claude (or any other tool) writes to the file.

## Installation

**VS Code Marketplace:**

```bash
code --install-extension deviationlabs.vscode-sidebar-notes
```

**Cursor Marketplace (Open VSX):**

Search **Sticky Sidebar Notes** by `deviationlabs` in the Cursor Extensions panel, or install the `.vsix` directly:

```bash
cursor --install-extension vscode-sidebar-notes-0.1.0.vsix
```

## Features

- **Always editable**: the sidebar is a plain textarea — no toggle needed, just start typing.
- **Immediate sync**: every keystroke saves to disk instantly. No debounce delay by default.
- **Live reload**: external edits (from Claude, `git pull`, another editor) refresh the sidebar immediately without losing your cursor position.
- **White background**: clean notepad aesthetic regardless of your editor theme.
- **Workspace-aware**: each workspace gets its own `sidebar-notes.md`. Falls back to a configurable global file when no workspace is open.
- **Published to both marketplaces**: available on VS Code Marketplace and Cursor (Open VSX).

## Usage

1. Click the **Sticky Sidebar Notes** icon in the activity bar.
2. The sidebar shows `sidebar-notes.md` from your workspace root — created automatically on first save.
3. Type directly in the sidebar; changes write to disk immediately.
4. Click the filename in the status line to open the file in a regular editor tab.
5. Have Claude write to the file and watch the sidebar update live:
   ```
   Append a one-paragraph summary of this session to sidebar-notes.md.
   ```

## Settings

| Setting | Default | Description |
| --- | --- | --- |
| `sidebarNotes.fileName` | `sidebar-notes.md` | Workspace-relative path of the notes file. |
| `sidebarNotes.globalFile` | _(empty)_ | Absolute path used when no workspace is open. |
| `sidebarNotes.debounceMs` | `0` | Milliseconds between keystroke and save. `0` = immediate. |

## Development

```bash
cd VSCodeSidebarNotes
npm install
npm run compile        # one-shot bundle → dist/extension.js
npm run watch          # rebuild on save
```

Press `F5` from this folder to launch an Extension Development Host.

### Packaging

```bash
npm run package          # production bundle
npm run package-vsix     # produces vscode-sidebar-notes-<version>.vsix
```

### Publishing

PATs are stored in `config/local.yaml` (gitignored) under `vscode_marketplace.pat` and `open_vsx.pat`.

**VS Code Marketplace:**

```bash
VSCE_PAT=$(python3 -c "from omegaconf import OmegaConf; c=OmegaConf.load('../config/local.yaml'); print(c.vscode_marketplace.pat)") npm run publish
```

**Cursor / Open VSX:**

```bash
OVSX_PAT=$(python3 -c "from omegaconf import OmegaConf; c=OmegaConf.load('../config/local.yaml'); print(c.open_vsx.pat)") npm run publish-cursor
```

To get new tokens: VS Code PAT from [dev.azure.com](https://dev.azure.com) (scope: Marketplace → Manage); Open VSX PAT from [open-vsx.org](https://open-vsx.org) (scope: publish).

## License

MIT — see [LICENSE](LICENSE).
