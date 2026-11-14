(() => {
  "use strict";

  const BRIDGE = "foxyforvps-fxa-bridge-v2";
  const TOKEN_PATTERN = /^[0-9a-f]{64}$/i;
  const ALLOWED_ORIGIN = "https://accounts.firefox.com";

  window.addEventListener("message", (event) => {
    if (event.source !== window || event.origin !== ALLOWED_ORIGIN) return;
    const message = event.data;
    if (!message || message.bridge !== BRIDGE || typeof message.token !== "string") return;
    if (!TOKEN_PATTERN.test(message.token)) return;

    // The background validates sender URL and tab ID and stores this only in storage.session.
    browser.runtime.sendMessage({ type: "foxy-capture-session", token: message.token })
      .catch(() => {});
  }, false);
})();
