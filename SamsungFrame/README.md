# Samsung Frame TV Art Manager

A Python client for managing art mode on Samsung Frame TVs. Upload images, configure display settings, and control slideshow playback remotely.

## Features

- **Batch Upload with HEIC Conversion**: Convert iPhone/iOS HEIC images to 4K JPG and upload
- **Recursive Directory Scanning**: Process images from nested subdirectories
- **Smart Filtering**: Exclude thumbnails and small files automatically
- **Matte Configuration**: Apply black borders (or other matte styles) to uploaded images
- **Art Mode Control**: Enable art mode and start automatic slideshow
- **TV Status**: Check connection and art mode support
- **Art Inventory**: List all available art on TV
- **Pushover Notifications**: Get notified of upload results and errors
- **Token-based Authentication**: Secure WebSocket connection with persistent token storage

## Setup

### Configuration

Add your Samsung Frame TV settings to `lib/Constants.py`:

```python
# Samsung Frame TV Configuration
SAMSUNG_FRAME_IP = "192.168.XX.YY"  # Your TV's IP address
SAMSUNG_FRAME_PORT = 8002  # WebSocket port (default: 8002)
SAMSUNG_FRAME_TOKEN_FILE = f"{TOKENS_DIR}/samsung_frame_token.txt"
SAMSUNG_FRAME_DEFAULT_MATTE = "shadowbox"  # Black border style
SAMSUNG_FRAME_SUPPORTED_FORMATS = ["jpg", "jpeg", "png"]
SAMSUNG_FRAME_MAX_IMAGE_SIZE_MB = 10

# Add to PUSHOVER_TOKENS dict for notifications
PUSHOVER_TOKENS = {
    # ... existing tokens ...
    "SamsungFrame": "your-pushover-token",
}
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
4. The authentication token will be automatically saved to `Constants.SAMSUNG_FRAME_TOKEN_FILE`
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

# Replace all existing user-uploaded art
uv run python SamsungFrame/batch_upload.py ~/Photos/Vacation --purge

# Custom matte
uv run python SamsungFrame/batch_upload.py ~/Photos --matte shadowbox_black
```

**What the batch upload script does:**

1. **Recursive Discovery**: Scans directory and all subdirectories for images
2. **Smart Filtering**: Excludes files <1MB (configurable) and thumbnail patterns (*_thumb*, *_thumbnail*, *_small*)
3. **HEIC Conversion**: Converts HEIC to high-quality JPG at 4K resolution (maintains aspect ratio, max 3840×2160)
4. **Quality Compression**: Reduces JPG quality (95→90→85→80→75→70) if needed to meet 10MB TV limit
5. **Delete Existing Art**: Optionally removes all user-uploaded art (preserves Samsung pre-loaded art)
6. **Batch Upload**: Uploads all processed images with specified matte
7. **Enable Art Mode**: Automatically enables slideshow after upload

**Command Options:**

- `source_dir` - Directory to scan (required)
- `--matte` - Matte style (default: shadowbox_black)
- `--purge` - Delete all user-uploaded art before upload

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

**Note**: This is different from the TV's built-in slideshow. The cycle-images command gives you precise control over timing and which images to display.

## Architecture

### Core Components

- **`samsung_client.py`**: Core client class (`SamsungFrameClient`)
  - Connection management with retry logic
  - Image validation and upload
  - Art mode control
  - Slideshow management

- **`manage_samsung.py`**: CLI entry point
  - Argparse-based command interface
  - Upload workflow orchestration
  - Pushover notification integration

- **`test_samsung_client.py`**: Comprehensive test suite
  - Unit tests with mocked TV connections
  - Image validation tests
  - Upload workflow tests

### Data Models (Pydantic)

- **`UploadResult`**: Single image upload result with success/error details
- **`ImageUploadSummary`**: Batch upload summary with counts and error list

### Dependencies

- **`samsungtvws`**: Samsung TV WebSocket API library
- **`Pillow`**: Image validation and processing
- **`pydantic`**: Data validation and modeling

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
- Verify IP address in `lib/Constants.py` is correct
- Check firewall isn't blocking port 8002

### Authentication Failed

**Symptoms**: Connection works but commands fail with auth errors

**Solutions**:
- Delete token file (check `Constants.SAMSUNG_FRAME_TOKEN_FILE`): `rm lib/tokens/samsung_frame_token.txt`
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

If you see permission errors, ensure token file (from `Constants.SAMSUNG_FRAME_TOKEN_FILE`) has restrictive permissions:

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

## References

- [samsung-tv-ws-api GitHub](https://github.com/xchwarze/samsung-tv-ws-api)
- Samsung Frame TV User Manual
- [Pushover API Documentation](https://pushover.net/api)
