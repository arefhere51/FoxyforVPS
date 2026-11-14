# FoxyforVPS Firefox Login Bridge

This temporary Firefox WebExtension is an experimental login bridge for the self-hosted panel. It never asks for or reads the Firefox Account password. Version 0.2.0 listens for Firefox Accounts' WebChannel event in a small `MAIN`-world page hook, then relays only a validated 64-character session token through the isolated content script. The background stores the token in `browser.storage.session` (memory for the browser session, not disk), tied to the originating tab, for at most ten minutes. The popup consumes it once and the backend exchanges it for OAuth credentials.

## Load temporarily

1. Keep either the SSH tunnel open:
   `ssh -L 8777:127.0.0.1:8778 USER@VPS`
   or configure the panel with a public HTTPS hostname on port 8777.
2. In the panel, authenticate and create a one-use pairing code (10-minute expiry).
3. In Firefox 128+, visit `about:debugging#/runtime/this-firefox`, select **Load Temporary Add-on…**, and choose `manifest.json` in this folder.
4. Open the extension popup and press **Open official Firefox sign-in**. The button opens the official login flow with `service=sync&context=fx_desktop_v3`.
5. Sign in normally in that same tab. After Firefox redirects to account settings, leave that tab open.
6. In the popup, enter the panel URL (`http://127.0.0.1:8777` through SSH, or `https://your-hostname:8777`), paste the pairing code, and press send. For a public HTTPS hostname, Firefox will request optional permission for that one host after the click.

For the local option, the SSH tunnel maps the computer's `127.0.0.1:8777` to the VPS's private `127.0.0.1:8778`. For public access, the backend remains loopback-only and Caddy terminates TLS at `https://hostname:8777`; do not use plain HTTP on the public Internet.

The token is deleted from extension session storage when consumed and is never written to `storage.local`. If the extension is removed on browser close, load it again. The bridge is not a Mozilla-supported integration and may stop working if Firefox changes its WebChannel behavior or the network rejects the sign-in request.
