# Firefox Accounts sign-in flow

## How FoxyVPN Android signs in

The Android implementation opens the official Firefox Accounts flow in a WebView, bridges the Firefox WebChannel login event, and receives a `sessionToken`. The application then exchanges that session for OAuth credentials and asks Firefox Accounts to destroy the temporary session token (best effort).

Source references:

- https://github.com/Vauth/FoxyVPN/blob/main/app/src/main/java/com/vauth/foxyvpn/ui/screens/BrowserLoginScreen.kt
- https://github.com/Vauth/FoxyVPN/blob/main/app/src/main/java/com/vauth/foxyvpn/data/FxaAuthRepository.kt

## Current FoxyforVPS flow

The panel opens the official Firefox Accounts Sync sign-in page with `context=fx_desktop_v3`, `service=sync`, and `action=email`. A narrowly scoped Firefox extension listens for the page's WebChannel messages `fxaccounts:login` and `fxaccounts:oauth_login`. The extension returns the session token to the exact opener origin only after a user confirmation dialog.

The Firefox password and verification codes stay in Mozilla's page. The temporary session token is sent to the VPS over HTTPS or an SSH tunnel, held only in memory for at most 15 minutes, and checked while the user completes email/TOTP verification in the open browser page. Once verified, the backend exchanges it for the OAuth credentials needed by the VPN service and asks FxA to destroy the temporary session. OAuth credentials remain persisted on the VPS.

The bridge attempt is same-origin protected and bound to a random nonce. It does not expose a password form on the VPS and does not store the session token on disk.

## Anti-bot and transport boundary

This is an unofficial integration based on the WebChannel flow used by Firefox Sync clients. It is not Mozilla's general OAuth integration. Public OAuth relying parties need registered clients and redirect URIs. WebChannel details or Firefox site behavior may change.

Opening the page in a real Firefox browser can avoid sending the password from a VPS network fingerprint, but the session-status and OAuth requests still originate from the VPS. Either can still be blocked with HTTP 406. FoxyforVPS does not automate CAPTCHA or bypass anti-bot challenges.

For installation and user-visible security details, see [browser-login.md](browser-login.md).
