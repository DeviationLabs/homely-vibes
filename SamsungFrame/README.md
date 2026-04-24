# Samsung Frame TV Art Manager

A Python client for managing art mode on Samsung Frame TVs. Upload images, configure display settings, and control slideshow playback remotely.

## Features

- **Batch Upload with HEIC Conversion**: Convert iPhone/iOS HEIC images to 4K JPG and upload
- **Recursive Directory Scanning**: Process images from nested subdirectories
- **Smart Filtering**: Exclude thumbnails and small files automatically
- **Filename Trimming**: Automatically trims filenames to <50 chars (preserves extension, handles collisions)
- **Start Index / Pagination**: Skip first N files with `--start-index` for resuming interrupted uploads
- **Smart Purge**: Delete stale art (uploaded >24h ago or untracked) while respecting minimum image count
- **Connection Health Checks**: Automatically stops uploads after consecutive failures to avoid wasting time on unstable connections
- **Upload History Tracking**: Local JSON tracker records upload timestamps for time-based purge decisions
- **Matte Configuration**: Apply black borders (or other matte styles) to uploaded images
- **Art Mode Control**: Enable art mode and start automatic slideshow
- **TV Status**: Check connection and art mode support
- **Art Inventory**: List all available art on TV
- **Pushover Notifications**: Get notified of upload results and errors
- **Token-based Authentication**: Secure WebSocket connection with persistent token storage

## Setup

### Configuration

Add your Samsung Frame TV settings to `config/local.yaml`:

```yaml
samsung_frame:
  ip: "192.168.XX.YY"  # Your TV's IP address
  port: 8002  # WebSocket port (default: 8002)
  token_file: lib/tokens/samsung_frame_token.txt
  default_matte: shadowbox  # Black border style
  supported_formats: [jpg, jpeg, png]
  max_image_size_mb: 10

# Add to pushover tokens for notifications
pushover:
  tokens:
    SamsungFrame: your-pushover-token
```

### Installation

Install dependencies from the project root:

```bash
uv sync
```

### First-Time Authentication

On first run, any command that connects to the TV will display a pairing prompt:

```bash
# Option 1: Use status command to pair without uploading
uv run python SamsungFrame/manage_samsung.py status

# Option 2: Pair during first upload
uv run python SamsungFrame/batch_upload.py /path/to/images
```

**Pairing Steps:**
1. Run any command that connects to TV (status, batch upload, list-art, etc.)
2. Check your TV screen for the pairing prompt
3. Accept the connection on your TV
4. The authentication token will be automatically saved to `config samsung_frame.token_file`
5. Subsequent operations will use the saved token without requiring TV approval

**To re-pair:** Delete the token file and run any connection command:

```bash
rm lib/tokens/samsung_frame_token.txt
uv run python SamsungFrame/manage_samsung.py status
```

## Usage

All commands should be run from the project root directory.

### Batch Upload with HEIC Conversion

For iPhone/iOS users with HEIC photos, use the batch upload script which handles conversion automatically:

```bash
# Basic batch upload with HEIC conversion
uv run python SamsungFrame/batch_upload.py ~/Photos/Favorites

# Purge stale art (>24h old or untracked) after upload
uv run python SamsungFrame/batch_upload.py ~/Photos/Vacation --purge

# Custom matte
uv run python SamsungFrame/batch_upload.py ~/Photos --matte shadowbox_black

# Skip first 20 files (resume interrupted upload)
uv run python SamsungFrame/batch_upload.py ~/Photos --start-index 20

# Upload at most 50 files starting from index 10
uv run python SamsungFrame/batch_upload.py ~/Photos --start-index 10 --max-files 50
```

**What the batch upload script does:**

1. **Recursive Discovery**: Scans directory and all subdirectories for images
2. **Smart Filtering**: Excludes files <1MB (configurable) and thumbnail patterns (*_thumb*, *_thumbnail*, *_small*)
3. **Start Index / Max Files**: Optionally skip first N files and/or cap total uploads
4. **Phase 1 — Prepare**: Converts HEIC to high-quality JPG at 4K (max 3840×2160), copies JPG/PNG, trims all filenames to <50 chars
5. **Quality Compression**: Reduces JPG quality (95→90→85→80→75→70) if needed to meet 10MB TV limit
6. **Phase 2 — Upload**: Uploads all prepared images with health checking (stops after 3 consecutive failures)
7. **Upload Tracking**: Records upload timestamps locally for time-based purge
8. **Smart Purge**: Optionally deletes art uploaded >24h ago or untracked (respects minimum image count)
9. **Enable Art Mode**: Automatically enables slideshow after upload

**Command Options:**

- `source_dir` - Directory to scan (required)
- `--matte` - Matte style (default: shadowbox_black)
- `--purge` - Delete stale art (>24h old or untracked) after upload
- `--start-index N` - Skip first N discovered files (applied before --max-files)
- `--max-files N` - Maximum number of files to upload (0 = all)

**Note**: Pushover notifications sent automatically. Files <1MB filtered as thumbnails.

**Supported Formats**: HEIC, JPG, JPEG, PNG

### Check TV Status

Check TV connection and display comprehensive information:

```bash
uv run python SamsungFrame/manage_samsung.py status
```

Example output:
```
Connecting to Samsung Frame TV at 192.168.1.4...
==================================================
TV STATUS
==================================================
Model: QN55LS03FADXZA
Name: 55" The Frame
Firmware: Unknown
Resolution: 3840x2160
Power State: on
OS: Tizen
Network Type: wireless
Frame TV Support: true
Available Art: 42 items
Art Mode: Supported and working
```

**Note:** Status command uses REST API only, so it won't trigger the pairing prompt. Run an upload command first to establish authentication.

### List Available Art

List all art currently on the TV:

```bash
uv run python SamsungFrame/manage_samsung.py list-art
```

### List Available Matte Styles

See what matte (border) styles your TV supports:

```bash
uv run python SamsungFrame/manage_samsung.py list-mattes
```

Common options include: `shadowbox`, `none`, `modern`, `flexible`, `panoramic`

### Download Thumbnails

Download thumbnail images for your uploaded photos:

```bash
# Download only user-uploaded photos
uv run python SamsungFrame/manage_samsung.py download-thumbnails ~/Downloads/samsung_thumbnails

# Download all art (including Samsung's pre-installed art)
uv run python SamsungFrame/manage_samsung.py download-thumbnails ~/Downloads/samsung_thumbnails --all
```

### Update Mattes for Existing Art

Change the matte (border) style for all art already on the TV:

```bash
# Update all art to default black border
uv run python SamsungFrame/manage_samsung.py update-mattes

# Update with base style only
uv run python SamsungFrame/manage_samsung.py update-mattes --matte shadowbox

# Update with style and color (e.g., shadowbox with black color)
uv run python SamsungFrame/manage_samsung.py update-mattes --matte shadowbox_black
uv run python SamsungFrame/manage_samsung.py update-mattes --matte modern_warm
uv run python SamsungFrame/manage_samsung.py update-mattes --matte flexible_polar
```

**Matte Format**: `<base_style>` or `<base_style>_<color>`

Valid colors: seafoam, black, neutral, antique, warm, polar, sand, sage, burgandy, navy, apricot, byzantine, lavender, redorange, skyblue, turqoise

This command:

- Retrieves all art currently on the TV
- Validates matte style and optional color
- Updates each art item to use the specified matte style
- Reports success/failure/skipped counts

### Start Slideshow

Enable the TV's automatic slideshow feature (recommended for normal use):

```bash
# Start slideshow with default settings (15 min interval, shuffle on)
uv run python SamsungFrame/manage_samsung.py start-slideshow

# Custom interval (30 minutes between images)
uv run python SamsungFrame/manage_samsung.py start-slideshow --duration 30

# Sequential mode (no shuffle)
uv run python SamsungFrame/manage_samsung.py start-slideshow --no-shuffle
```

This command:

- Enables art mode on the TV
- Starts the TV's built-in slideshow for user-uploaded photos
- Configures the interval between image changes (in minutes)
- Optionally enables shuffle or sequential mode
- Returns after starting the slideshow (TV continues cycling independently)

**Note**: This uses the TV's native slideshow feature, which continues running even after the command exits. The TV will cycle through images automatically based on the configured interval.

### Cycle Through Images

Manually cycle through your photos with a specified period (useful for testing or presentations):

```bash
# Cycle through user photos every 15 seconds (default)
uv run python SamsungFrame/manage_samsung.py cycle-images

# Custom period (30 seconds)
uv run python SamsungFrame/manage_samsung.py cycle-images --period 30

# Cycle through all art (including Samsung's pre-installed art)
uv run python SamsungFrame/manage_samsung.py cycle-images --all --period 10
```

This command:

- Enables art mode on the TV
- Retrieves all available art (or only user-uploaded photos)
- Cycles through each image with the specified period
- Continues indefinitely until you press Ctrl+C
- Logs each image change for monitoring

**Note**: This is different from the TV's built-in slideshow. The cycle-images command gives you precise control over timing (in seconds) and which images to display, but requires the script to keep running.

## Architecture

### Core Components

- **`samsung_client.py`**: Core client class (`SamsungFrameClient`)
  - Connection management with retry logic
  - Image validation and upload with health checking (consecutive failure detection)
  - Art mode control
  - Slideshow management

- **`batch_upload.py`**: Batch upload with two-phase architecture
  - Phase 1: Prepare images (HEIC conversion, filename trimming, copy to temp dir)
  - Phase 2: Upload via `upload_images_from_folder()` with automatic health checks
  - Smart purge using local upload history tracking

- **`upload_tracker.py`**: Local upload history (JSON-based)
  - Records content_id → timestamp for each upload
  - Identifies stale art (>24h or untracked) for purge
  - Stored at `config/samsung_upload_history.json` (gitignored)

- **`manage_samsung.py`**: CLI entry point
  - Argparse-based command interface for TV management
  - Pushover notification integration

- **`test_batch_upload.py`**: Comprehensive test suite
  - Tests for discovery, conversion, deletion, filename trimming, upload tracking, start-index

### Data Models (Pydantic)

- **`UploadResult`**: Single image upload result with success/error details
- **`ImageUploadSummary`**: Batch upload summary with counts and error list

### Dependencies

- **`samsungtvws`**: Samsung TV WebSocket API library (using [NickWaterton fork v3.0.5+](https://github.com/NickWaterton/samsung-tv-ws-api) for improved upload reliability)
- **`Pillow`**: Image validation and processing
- **`pydantic`**: Data validation and modeling

**Note**: This project uses the NickWaterton fork of samsungtvws which includes critical fixes for image uploads, particularly for TVs with `support_myshelf: FALSE`. The official pypi package (v2.7.2) has known issues with large file uploads.

## Supported Matte Styles

Use the `list-mattes` command to see what your TV supports. Common options:

- `shadowbox` - Black border (default)
- `none` - No border
- `modern`, `modernthin`, `modernwide` - Modern border styles
- `flexible` - Flexible border
- `panoramic` - Panoramic layout
- `triptych` - Three-panel layout
- `mix` - Mixed layout
- `squares` - Square grid layout

Run `uv run python SamsungFrame/manage_samsung.py list-mattes` to see your TV's exact options.

## Troubleshooting

### Cannot Connect to TV

**Symptoms**: `Failed to connect to TV at 192.168.1.4`

**Solutions**:
- Verify TV is powered on (not fully off)
- Check TV is on same network as computer running script
- Verify IP address in `config/local.yaml` (samsung_frame.ip) is correct
- Check firewall isn't blocking port 8002

### Authentication Failed

**Symptoms**: Connection works but commands fail with auth errors

**Solutions**:
- Delete token file: `rm lib/tokens/samsung_frame_token.txt`
- Run status command again and accept pairing prompt on TV
- Ensure token file has correct permissions (600)

### Image Upload Fails

**Symptoms**: Some or all images fail to upload

**Common causes**:
- **Unsupported format**: Only JPG and PNG supported
- **File too large**: Images must be < 10MB
- **Corrupted file**: File cannot be opened by PIL
- **Network timeout**: TV connection unstable

**Check logs** for specific error messages about failed images.

### Art Mode Not Supported

**Symptoms**: `Art mode: Not supported or unavailable`

**Solutions**:
- Verify you have a Samsung Frame TV (or other model with art mode)
- Ensure TV firmware is up to date
- Try restarting the TV

### Token File Permissions

If you see permission errors, ensure token file has restrictive permissions:

```bash
chmod 600 lib/tokens/samsung_frame_token.txt
```

## Development

### Running Tests

```bash
# Run all SamsungFrame tests
uv run python -m pytest SamsungFrame/ -v

# Run specific test
uv run python -m pytest SamsungFrame/test_samsung_client.py::TestSamsungFrameClient::test_upload_image_success -v
```

### Linting

```bash
# Run all linters
make lint

# Auto-fix issues
make lint-fix
```

## Technical Notes

### Image Validation

Before upload, each image is validated:
1. File exists and is readable
2. Extension matches supported formats
3. File size is within limits
4. PIL can successfully open and verify the image

Invalid images are skipped with logged errors.

### Connection Retry Logic

Connection attempts use exponential backoff:
- Max 3 attempts
- Initial retry delay: 2 seconds
- Delay doubles on each retry (2s, 4s)

### Token Security

- Token file stored in `~/logs/` with 600 permissions (owner read/write only)
- Token automatically saved on first successful pairing
- No credentials stored in code or logs

### Slideshow Behavior

The slideshow uses the TV's configured rotation interval (fastest available). The interval cannot be customized via the API - adjust it directly on the TV's art mode settings.

## Validated Batch Upload Sessions

Cross-reference with `~/bin/_claude/shared-memory/skills/samsung.md` for full protocol notes.

| Date | TV Model | Firmware | Images | Success | Runtime | Notes |
|------|----------|----------|--------|---------|---------|-------|
| 2026-04-23 | QN55LS03FADXZA (55" Frame) | unknown | 474 | 472 (99.6%) | 1h 38m | 2 WebSocket timeout failures; Art API toggled ×2; `ms.channel.timeOut` retry bug fixed same day |

**Observed failure modes (all auto-recovered except where noted):**
- `ms.channel.timeOut` on initial connect → retry with backoff (requires fix in `connect()`)
- Mid-upload WebSocket timeout → 10s cooldown, skip image, continue *(image lost)*
- Art API unresponsive mid-run → `KEY_POWER` toggle, reconnect, resume *(no image loss)*
- `ms.channel.clientDisconnect` response → treated as failure, next image normal

## References

- [NickWaterton samsung-tv-ws-api fork](https://github.com/NickWaterton/samsung-tv-ws-api) (v3.0.5+ used by this project)
- [Original samsung-tv-ws-api](https://github.com/xchwarze/samsung-tv-ws-api) (official upstream)
- Samsung Frame TV User Manual
- [Pushover API Documentation](https://pushover.net/api)
