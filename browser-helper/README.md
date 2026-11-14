# FoxyforVPS Firefox Login Bridge (experimental)

This temporary Firefox WebExtension is an optional login bridge for the self-hosted panel. It does not ask for or read the Firefox Account password. It watches only `WebChannelMessageToChrome` events on `https://accounts.firefox.com/*`, holds a verified 64-hex session token in the active tab's memory, and sends it only after the user explicitly presses the popup button.

The session token is posted to `http://127.0.0.1:8777/api/account/browser-session`, which is expected to be the local end of an SSH port forward to the VPS. The panel requires a high-entropy, one-use pairing code that expires after ten minutes. The backend validates the code, exchanges the session token for OAuth tokens, and never writes the short-lived session token to disk.

## Load temporarily

1. Establish and keep open `ssh -L 8777:127.0.0.1:8777 USER@VPS`.
2. Open the dashboard, authenticate as panel admin, and create a browser-login pairing code.
3. In desktop Firefox, visit `about:debugging#/runtime/this-firefox`.
4. Choose **Load Temporary Add-on…** and select `manifest.json` in this folder.
5. Open the official `accounts.firefox.com` login page in Firefox and complete the normal login.
6. Click the extension button, paste the pairing code, and click its send button.

Firefox temporary add-ons are removed after the browser closes. The WebChannel event behavior is based on the FoxyVPN Android WebView integration and has not been validated against every Firefox desktop release/account state. If no login message arrives or Mozilla returns an anti-bot challenge (HTTP 406), do not enter the password into this project; the flow is unsupported in that environment.
