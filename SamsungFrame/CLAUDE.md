# Samsung Frame TV Module

## Bootstrap
Always load config before making live API calls or constructing clients:
```python
from lib.config import get_config
cfg = get_config()
token_file = cfg.samsung_frame.token_file
tv_ip = cfg.samsung_frame.ip
```
Use `SamsungFrameClient()` which reads config automatically. Never hardcode paths or IPs.

## Architecture
- `samsung_client.py` — WebSocket client wrapping `samsungtvws` (NickWaterton fork v3.0.5)
- `batch_upload.py` — Two-phase upload workflow (prepare temp dir -> upload)
- `manage_samsung.py` — CLI entry point with subcommands
- Config keys: `cfg.samsung_frame.ip`, `.port`, `.token_file`, `.default_matte`, `.min_images`, `.min_size_mb`, `.slideshow_delay_seconds`

## TV Art API
See `~/.claude/learnings/skills/samsung.md` for full API schema and protocol details.

Key for this codebase:
- `image_date` available from API — usable for age-based purge directly
- No filename or file hash returned — no dedup possible
- Art channel only responds when TV is in art mode

## Stability Features
- `ping()` — `art().supported()` as health check
- `get_available_art_strict()` — raises on error (vs `get_available_art()` returns `[]`)
- `_reconnect()` — close + sleep(2) + reconnect
- `_reboot_and_reconnect()` — reboot TV + exponential backoff (30s→5min, 5 attempts) + reconnect
- Upload loop: 3 consecutive failures → reboot TV → backoff reconnect → resume; abort if reboot fails
- Post-timeout verification: checks TV art list for new IDs when upload returns None/error
- 5s pause between uploads for TV stability
- `--timeout` CLI param (default 60s) forwarded to `SamsungTVWS`
- Purge runs even after upload abort (reconnects if needed)

## Purge Logic
- Purge is ON by default; use `--no-purge` to skip
- `get_stale_art_ids()` uses `image_date` from TV API — no local state needed for age
- `min_images` config value is safety cap against deleting everything
- Art with empty `image_date` (Samsung pre-installed or very old uploads) treated as stale

## CLI Commands
- `batch_upload.py <source_dir>` — `--no-purge`, `--start-index`, `--max-files`, `--timeout`, `--matte`
- `manage_samsung.py status|list-art|list-mattes|delete-all|download-thumbnails|update-mattes|cycle-images|start-slideshow|reboot`

## Testing
- Tests in `test_samsung_client.py` and `test_batch_upload.py`
- Must patch `SamsungFrame.samsung_client.cfg` (not `get_config`) for module-level config
- `SamsungTVWS` constructor patched via `@patch("SamsungFrame.samsung_client.SamsungTVWS")`
