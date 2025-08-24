# BrowserAlert - Web Usage Monitoring System

A web usage monitoring and alerting system for tracking browsing activity and implementing parental controls through Chrome history analysis and network-level blocking.

## Overview

This system monitors web browsing activity by analyzing Chrome browser history and implements content filtering through router-level blocking. It's designed for parental control scenarios where you need to track and limit web access.

## Prerequisites

### Network Setup
- **Static IP**: 192.168.1.24
- **Network**: Ensure device is on main network (Aerosol), not guest network
  - Check from Deco Device page
  - If on Guest network, disable Guest on Deco to force device to roam back
- **Required Packages**: brew, eternal terminal, sqlite3

### System Architecture
- Router-level blocking through Deco mesh system
- Chrome history analysis via SQLite queries
- Remote SSH monitoring for automated checks

## Target Device Configuration

### macOS Device Setup (Rian's Laptop)

#### Screen Time Controls
- Activate Screen Time on phone and MacBook Air
- Safari limited to 1 minute screen time (effectively disabled)
- Removed admin privileges for monitored user

#### System Configuration
- Disabled power saving when plugged in
- Created monitoring user: "abutala"
- Enabled remote SSH access

#### SSH Configuration
Reference: [Apple Remote Access Guide](https://support.apple.com/guide/mac-help/allow-a-remote-computer-to-access-your-mac-mchlp1066/mac)

**Sudoers Configuration** (`/private/etc/sudoers.d/`):
```bash
abutala ALL=(ALL) NOPASSWD:ALL
```

**SSH Daemon Configuration** (`/etc/ssh/sshd_config`):
```bash
ClientAliveInterval 15
ClientAliveCountMax 3
MaxSessions 255
```
*Note: MaxSessions allows multiple connections with completed/dead sessions lasting 45 seconds*

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
/Users/rianbutala/Library/Application Support/Google/Chrome/Default/History
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
ssh abutala@192.168.1.24
sqlite3 "/Users/rianbutala/Library/Application Support/Google/Chrome/Default/History" < query.sql
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
- Issues: Redirects became messy, multiple redirect chains to tplink router

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
ErrorDocument 404 http://192.168.1.1:30000/shn_blocking.html?cat_id=100&domain=EDEN_Inc_Not_Allowed/

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

- SSH access requires secure key management
- Browser history contains sensitive personal data
- Network-level blocking may affect legitimate usage
- Regular monitoring of system logs recommended