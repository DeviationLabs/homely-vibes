# Changelog

## 0.1.1

- Re-publish to Open VSX with verified namespace ownership.

## 0.1.0

- **Always-edit mode**: removed preview/edit toggle; sidebar is a plain textarea, always editable.
- **White background**: hardcoded `#ffffff` background regardless of editor theme — clean notepad aesthetic.
- **Immediate save**: `debounceMs` default changed from 400 → 0; every keystroke writes to disk instantly.
- **Cursor Marketplace**: published to Open VSX Registry so the extension appears in Cursor's built-in marketplace.
- Removed `markdown-it` dependency (no longer needed without preview rendering).

## 0.0.1 — initial release

- Webview sidebar that reads `sidebar-notes.md` from the workspace root.
- Live reload on external file change (so Claude / other tools writing to the file are reflected immediately).
- Edit/preview toggle, debounced save back to disk.
- Configurable file name, global-file fallback, and save debounce.
- Successor to the original "Sidebar Notes" extension; fixes its typos and adds disk persistence.
