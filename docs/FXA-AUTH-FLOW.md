# Firefox Accounts sign-in flow

## How FoxyVPN Android signs in

The Android implementation opens the official Firefox Accounts flow in a WebView, bridges the Firefox WebChannel login event, and receives a `sessionToken`. The application then exchanges that session for OAuth credentials and asks Firefox Accounts to destroy the temporary session token (best effort).

Source references:

- https://github.com/Vauth/FoxyVPN/blob/main/app/src/main/java/com/vauth/foxyvpn/ui/screens/BrowserLoginScreen.kt
- https://github.com/Vauth/FoxyVPN/blob/main/app/src/main/java/com/vauth/foxyvpn/data/FxaAuthRepository.kt

## Current FoxyforVPS flow

The web panel does not use the browser extension or headless Chromium. It sends the email and password to the authenticated VPS backend over HTTPS (or an SSH tunnel). The backend derives FxA `authPW` using the account protocol and submits a direct `POST /v1/account/login` request. The plaintext password is not sent to the FxA login endpoint and is not written to persistent storage, command-line arguments, environment variables, or application logs.

If FxA requires email-code or TOTP verification, the API returns a temporary session token. FoxyforVPS keeps that token only in process memory, keyed by a random one-time attempt ID, with a 15-minute expiry and a five-try verification limit. Email-code and TOTP responses are submitted with Hawk authentication; email-link verification can be continued after the user clicks the link. Temporary attempts are deleted on completion/cancellation and disappear on process restart. The session token is exchanged through the existing OAuth path and a best-effort session-destroy request is made.

A blocked-login response can trigger Firefox's email unblock-code flow. The password is not retained by the server: the user re-enters it together with the emailed unblock code. The backend sends only the derived `authPW` in the subsequent FxA login request.

## Anti-bot and transport boundary

The API-login structure and derivation were inspected in the public Arman VPN client source:

- https://github.com/armanlife/arman-vpn-client/blob/main/core/internal/fxa/fxa.go
- https://github.com/armanlife/arman-vpn-client/blob/main/core/internal/fxa/hawk.go
- https://github.com/armanlife/arman-vpn-client/blob/main/core/internal/service/signin_flow.go

FoxyforVPS implements the direct login request and verification stages, but does **not** port Arman's custom HTTP-406/Fastly challenge solver. If Firefox Accounts responds with HTTP 406, FoxyforVPS reports the challenge and stops. It does not automate CAPTCHA or anti-bot challenge solving. The API, server-side policy, network egress and account security settings can all prevent direct login; success is not guaranteed.

## Credential boundary

The Firefox password traverses the VPS connection, so public panel access must use HTTPS and private access should use SSH tunneling. Root on the VPS can inspect application memory. OAuth access/refresh credentials required by the service remain in `/var/lib/foxyforvps/`; raw Firefox password and temporary session attempts are not persisted.
