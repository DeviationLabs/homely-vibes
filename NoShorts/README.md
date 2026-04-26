# NoShorts

An iOS app that wraps YouTube in a `WKWebView` and removes all Shorts content, giving you a clean YouTube browsing experience focused on regular videos.

## Features

- Loads `youtube.com` with a desktop browser user agent
- Strips Shorts shelf from the home feed
- Removes the Shorts tab from the sidebar and mini-guide
- Blocks navigation to any `/shorts/` URL (redirects to home)
- Filters Shorts from search results
- Simple toolbar: back, forward, home, reload

## Requirements

- macOS with Xcode 16+
- iOS 17+ device or simulator
- Apple ID (free tier sufficient for personal sideloading via AltStore)

## Setup

1. Open `NoShorts.xcodeproj` in Xcode
2. Select your team under **Signing & Capabilities** → your Apple ID
3. Connect your iPhone and select it as the run destination
4. Hit **Cmd+R** to build and install

For wireless re-signing without a paid developer account, use [AltStore](https://altstore.io).

## How It Works

JavaScript is injected into every page load via `WKUserScript`, removing Shorts DOM elements as they appear. A `MutationObserver` catches dynamically loaded content. Navigation to `/shorts/` paths is intercepted by `WKNavigationDelegate` and redirected to the YouTube home page.
