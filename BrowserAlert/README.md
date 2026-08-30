# BrowserAlert - Web Usage Monitoring System

A web usage monitoring and alerting system for tracking browsing activity and implementing parental controls through Chrome history analysis and network-level blocking.

## Overview

This system monitors web browsing activity by analyzing Chrome browser history and implements content filtering through router-level blocking. It's designed for parental control scenarios where you need to track and limit web access.

> **Consent note.** Monitoring someone else's browsing is lawful in some
> household contexts and not in others, and the ethics are separate from the
> legality. Know which applies to you before deploying this, and prefer
> transparent limits (Screen Time, DNS filtering) over undisclosed collection.

## Prerequisites

### Network Setup
- **Static IP**: assign the monitored device a static lease on the main LAN
- **Network**: ensure the device is on the main network, not the isolated
  guest/IoT network — guest client isolation blocks the SSH path below
- **Required Packages**: brew, eternal terminal, sqlite3

### System Architecture
- Router-level blocking through the mesh router's admin controls
- Chrome history analysis via SQLite queries
- Remote SSH monitoring for automated checks

## Target Device Configuration

### macOS Device Setup (monitored device)

#### Screen Time Controls
- Activate Screen Time on the monitored devices
- Safari limited to 1 minute screen time (effectively disabled)
- Removed admin privileges for monitored user

#### System Configuration
- Disabled power saving when plugged in
- Created monitoring user (dedicated account for this tool)
- Enabled remote SSH access

#### SSH Configuration
Reference: [Apple Remote Access Guide](https://support.apple.com/guide/mac-help/allow-a-remote-computer-to-access-your-mac-mchlp1066/mac)

**Sudoers Configuration** (`/private/etc/sudoers.d/`):

Grant only the specific commands the collector needs. A blanket
`NOPASSWD:ALL` turns any compromise of the monitoring account into
passwordless root on the device — scope it instead:

```bash
<monitor-user> ALL=(ALL) NOPASSWD: /usr/bin/sqlite3, /bin/cp
```

**SSH Daemon Configuration** (`/etc/ssh/sshd_config`):
```bash
ClientAliveInterval 15
ClientAliveCountMax 3
```
Prefer key-based auth and set `PasswordAuthentication no`. Raise `MaxSessions`
above the default only if you actually exhaust it — a high ceiling mostly
widens the window for connection-exhaustion noise.

## Chrome Browser Configuration

### Policy Configuration
Reference: [Chromium Policy List](https://www.chromium.org/administrators/policy-list-3)

```bash
# Disable browser history deletion
defaults write com.google.Chrome AllowDeletingBrowserHistory -bool false

# Disable incognito mode
defaults write com.google.Chrome IncognitoModeAvailability -integer 1

# Disable guest browsing
defaults write com.google.Chrome BrowserGuestModeEnabled -bool false

# Disable adding new browser profiles
defaults write com.google.Chrome BrowserAddPersonEnabled -bool false
```

### History Database Access

**Database Location**:
```
/Users/<monitored-user>/Library/Application Support/Google/Chrome/Default/History
```

**Query Recent History**:
```sql
SELECT 
    datetime(datetime(last_visit_time / 1000000 + (strftime('%s', '1601-01-01')), 'unixepoch'), 'localtime') as visit_time,
    url 
FROM urls 
ORDER BY last_visit_time DESC 
LIMIT 10;
```

## Remote Monitoring

Once SSH is configured, you can remotely access the device and pull browser history for analysis:

```bash
ssh <monitor-user>@<device-ip>
sqlite3 "/Users/<monitored-user>/Library/Application Support/Google/Chrome/Default/History" < query.sql
```

## Implementation Notes

### Successful Approaches
- Chrome policy enforcement through macOS defaults
- Remote SSH access for automated monitoring
- SQLite-based history analysis
- Router-level content blocking

### Failed Attempts

#### DNS-Based Filtering
- Attempted `/private/etc/hosts` modification
- Tried forcing SafeSearch via forcesafesearch.google.com
- Reference: [OpenDNS SafeSearch Guide](https://support.opendns.com/hc/en-us/articles/227986807-How-to-Enforcing-Google-SafeSearch-YouTube-and-Bing)
- Issues: Redirects became messy, multiple redirect chains to the router

#### DNS Cache Management
```bash
sudo dscacheutil -flushcache
sudo killall -HUP mDNSResponder
```
Also tried: `chrome://net-internals/#dns`

#### Apache-Based Blocking
Attempted redirect configuration:
```apache
# /etc/apache2/sites-enabled/000-default.conf
ErrorDocument 404 http://<block-page-host>:30000/shn_blocking.html?cat_id=100&domain=blocked/

# Test and restart
sudo apache2ctl configtest
sudo service apache2 restart
```

## Future Improvements

- Compress JSON and CSV log files for storage efficiency
- Implement automated alerting based on browsing patterns
- Add web dashboard for monitoring overview
- Integrate with time-based access controls

## Security Considerations

- SSH access requires secure key management; prefer keys over passwords
- Scope the sudoers grant to specific commands, never `ALL`
- Browser history contains sensitive personal data — treat collected history as
  sensitive at rest, and set a retention limit rather than keeping it forever
- Network-level blocking may affect legitimate usage
- Regular monitoring of system logs recommended
