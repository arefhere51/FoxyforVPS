(() => {
  "use strict";

  const BRIDGE = "foxyforvps-fxa-bridge-v2";
  const TOKEN_PATTERN = /^[0-9a-f]{64}$/i;
  const ALLOWED_HOST = "accounts.firefox.com";

  if (location.hostname !== ALLOWED_HOST) return;

  function parseObject(value) {
    if (typeof value === "string") {
      try { return JSON.parse(value); } catch (_) { return null; }
    }
    return value && typeof value === "object" ? value : null;
  }

  function onWebChannel(event) {
    try {
      const envelope = parseObject(event.detail);
      if (!envelope) return;
      const message = parseObject(envelope.message) || envelope;
      const command = String(message.command || "");
      if (command !== "fxaccounts:login" && command !== "fxaccounts:oauth_login") return;

      const data = parseObject(message.data) || {};
      const token = String(data.sessionToken || data.token || "").trim();
      if (!TOKEN_PATTERN.test(token)) return;

      // Only relay a structurally valid token; never log it or write it to disk.
      window.postMessage({ bridge: BRIDGE, token }, location.origin);
    } catch (_) {
      // Authentication payloads must never be logged.
    }
  }

  // FxA's WebChannel event is dispatched on the page's window/document.
  window.addEventListener("WebChannelMessageToChrome", onWebChannel, true);
  document.addEventListener("WebChannelMessageToChrome", onWebChannel, true);
})();
