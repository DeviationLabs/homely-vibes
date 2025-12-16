# Samsung Frame TV Art Manager

A Python client for managing art mode on Samsung Frame TVs. Upload images, configure display settings, and control slideshow playback remotely.

## Features

- **Image Upload**: Batch upload images from a local folder to TV
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
SAMSUNG_FRAME_TOKEN_FILE = f"{HOME}/logs/samsung_frame_token.txt"
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

On first run of an **upload** command, the TV will display a pairing prompt:

1. Run upload command: `uv run python SamsungFrame/manage_samsung.py upload /path/to/images`
2. Check your TV screen for the pairing prompt
3. Accept the connection on your TV
4. The authentication token will be automatically saved to `~/logs/samsung_frame_token.txt`
5. Subsequent uploads will use the saved token without requiring TV approval

**Important Notes:**

- Token is only saved during WebSocket operations (upload). The `status` command uses REST API and won't trigger token exchange.
- Once a token is saved, all operations (status, upload, list-art) will work without TV approval.

**To re-pair:** Delete the token file and run an upload command:

```bash
rm ~/logs/samsung_frame_token.txt
uv run python SamsungFrame/manage_samsung.py upload /path/to/images
```

## Usage

All commands should be run from the project root directory.

### Upload Images

Upload all images from a folder with default black border:

```bash
uv run python SamsungFrame/manage_samsung.py upload /path/to/images
```

Upload with custom matte style:

```bash
uv run python SamsungFrame/manage_samsung.py upload /path/to/images --matte modern_apricot
```

Upload with notification:

```bash
uv run python SamsungFrame/manage_samsung.py upload /path/to/images --notify
```

**What happens during upload:**
1. Connects to TV and validates art mode support
2. Scans folder for images (.jpg, .jpeg, .png)
3. Validates each image (format, size, readability)
4. Uploads images with specified matte style
5. Enables art mode
6. Starts slideshow with fastest rotation interval
7. Sends Pushover notification (on errors or if --notify flag used)

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

Common options include: `shadowbox` (black), `none`, `modern`, `flexible`, `panoramic`

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
- Delete token file: `rm ~/logs/samsung_frame_token.txt`
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
chmod 600 ~/logs/samsung_frame_token.txt
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
