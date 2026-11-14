# Firefox Accounts sign-in: client flow vs panel flow

## What FoxyVPN Android does

The Android implementation does not send a Firefox password to its backend. `BrowserLoginScreen.kt` opens the official Firefox Accounts login URL in an Android `WebView`, injects a small JavaScript listener for `WebChannelMessageToChrome`, exposes a `@JavascriptInterface` bridge, answers `fxaccounts:fxa_status` and `fxaccounts:can_link_account`, and receives the `sessionToken` from `fxaccounts:login`. `FxaAuthRepository.kt` then validates/exchanges the session token with Firefox Accounts and requests destruction of the session token after completing sign-in (the server-side destruction request is best-effort).

Source references:

- https://github.com/Vauth/FoxyVPN/blob/main/app/src/main/java/com/vauth/foxyvpn/ui/screens/BrowserLoginScreen.kt
- https://github.com/Vauth/FoxyVPN/blob/main/app/src/main/java/com/vauth/foxyvpn/data/FxaAuthRepository.kt

## FoxyforVPS direct-login implementation

The self-hosted web panel cannot receive a browser-internal WebChannel event from a regular cross-origin web page. To meet the requested panel-only workflow, the VPS runs a temporary headless Chromium session and uses a Playwright binding to mirror the limited WebChannel bridge above. It fills the official email/password form and only returns the 64-character session token to the Python process. The existing FxA code then exchanges it and requests destruction of the temporary session token (best-effort).

The Firefox password does cross the HTTPS connection to the VPS. Code does not put it in files, a database, process arguments, environment variables, or application logs; it is kept temporarily in request memory and sent to the separate browser process over stdin. The browser process runs under a dedicated unprivileged Linux user, has no persistent browser profile, and is closed after the login attempt. This does not protect credentials from the VPS root administrator. Public use requires HTTPS on the Caddy endpoint; the only HTTP use supported is local access through an SSH tunnel. CAPTCHA, MFA, email-verification, or other anti-automation checkpoints are not bypassed; those attempts fail without storing the password.

## Mozilla integration boundary

A conventional web OAuth callback is distinct from Firefox's WebChannel-based browser/desktop flow. Mozilla's relying-party guide requires a registered OAuth client and matching redirect URI; this project does not possess an OAuth client registered for the user's panel hostname.

- https://mozilla.github.io/ecosystem-platform/reference/webchannels
- https://mozilla.github.io/ecosystem-platform/relying-parties/tutorials/integration-with-fxa
