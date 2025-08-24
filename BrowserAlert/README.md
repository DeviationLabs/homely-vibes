Prerequisites    
Static IP: 192.168.1.24    
Ensure only on Aerosol. This can be checked from Deco Device page. If on Guest, then disable Guest on Deco to get laptop to roam back.     
Packages: brew, eternal terminal, sqlite3    
    
Rudimentary enforcement on Deco, but how do you find the bad sites. Deco can block, but finding and adding sites is hard. So, we look at google chrome history,    
    
Edits to Rian's Lappy:     
Activate screen time on phone and MBA (This is the only thing that helps with phone)    
Safari has screentime of 1 min, so effectively disabled.    
Removed admin privileges for Rian    
    
Disabled power saving when plugged in    
Created my own user: "abutala"    
Enabled remote ssh, and monitoring    
 <https://support.apple.com/guide/mac-help/allow-a-remote-computer-to-access-your-mac-mchlp1066/mac>   
Added to /private/etc/sudoers.d: "abutala ^I ALL=(ALL) NOPASSWD:ALL"    
"In /etc/ssh/sshd_config:
ClientAliveInterval 15
ClientAliveCountMax 3
MaxSessions 255
Allows MaxSessions) with completed/dead ones lasting 45 seconds"    
    
Rian's Google Chrome Config    
<https://www.chromium.org/administrators/policy-list-3>    
defaults write com.google.Chrome AllowDeletingBrowserHistory -bool false    
defaults write com.google.Chrome IncognitoModeAvailability -integer 1    
defaults write com.google.Chrome BrowserGuestModeEnabled -bool false    
defaults write com.google.Chrome BrowserAddPersonEnabled -bool false    
Run sqlite3 on: /Users/rianbutala/Library/Application Support/Google/Chrome/Default/History    
>> select datetime(datetime(last_visit_time / 1000000 + (strftime('%s', '1601-01-01')), 'unixepoch'), 'localtime'), url from urls order by last_visit_time desc limit 10;    
    
Now from my computer, I can ssh to Rian's laptop and pull his browser history. We are ready for scripting.     
    
Failed attempts    
 Enforce on /private/etc/hosts   
 forcesafesearch.google.com   
 <https://support.opendns.com/hc/en-us/articles/227986807-How-to-Enforcing-Google-SafeSearch-YouTube-and-Bing>   
 Most have been redirected to omega, where landing page further redirects to tplink. This is messy and needs a cleanup.    
 sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder   
 Also: in chrome: chrome://net-internals/#dns   
    
 We redirect everything to omega, and have apache server do the right thing   
 sudo vi /etc/apache2/sites-enabled/000-default.conf   
   ErrorDocument 404 http://192.168.1.1:30000/shn_blocking.html?cat_id=100&domain=EDEN_Inc_Not_Allowed/   
 sudo apache2ctl configtest   
 sudo service apache2 restart   
 Misc: compress json and csv files.    
    
    
    
    
    
    
    
    