let capturedSession = null;
const tokenPattern = /^[0-9a-f]{64}$/i;

function parseEnvelope(raw) {
  let envelope = raw;
  if (typeof envelope === "string") {
    try { envelope = JSON.parse(envelope); } catch (_) { return null; }
  }
  if (!envelope || typeof envelope !== "object") return null;
  let message = envelope.message || envelope;
  if (typeof message === "string") {
    try { message = JSON.parse(message); } catch (_) { return null; }
  }
  const command = String(message.command || "");
  if (command !== "fxaccounts:login" && command !== "fxaccounts:oauth_login") return null;
  const data = message.data || {};
  const token = String(data.sessionToken || data.token || "").trim().toLowerCase();
  return tokenPattern.test(token) ? token : null;
}

function capture(event) {
  try {
    const token = parseEnvelope(event.detail);
    if (token) capturedSession = token;
  } catch (_) {
    // Do not log or expose authentication payloads.
  }
}

window.addEventListener("WebChannelMessageToChrome", capture, true);
document.addEventListener("WebChannelMessageToChrome", capture, true);

browser.runtime.onMessage.addListener((message) => {
  if (message && message.type === "foxy-take-session") {
    const token = capturedSession;
    capturedSession = null;
    return Promise.resolve({ token });
  }
});
