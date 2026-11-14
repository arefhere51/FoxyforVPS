"use strict";

const STORAGE_KEY = "foxyforvpsCapturedSession";
const TOKEN_PATTERN = /^[0-9a-f]{64}$/i;
const MAX_AGE_MS = 10 * 60 * 1000;

function isAccountsUrl(value) {
  try { return new URL(value).origin === "https://accounts.firefox.com"; }
  catch (_) { return false; }
}

browser.runtime.onMessage.addListener((message, sender) => {
  if (!message || typeof message !== "object") return undefined;

  if (message.type === "foxy-capture-session") {
    const token = String(message.token || "");
    const tabId = sender.tab && sender.tab.id;
    if (!isAccountsUrl(sender.url || "") || !Number.isInteger(tabId) || !TOKEN_PATTERN.test(token)) {
      return Promise.resolve({ ok: false });
    }
    return browser.storage.session.set({
      [STORAGE_KEY]: { token, tabId, capturedAt: Date.now() }
    }).then(() => ({ ok: true }));
  }

  if (message.type === "foxy-take-session") {
    const tabId = Number(message.tabId);
    if (!Number.isInteger(tabId) || !sender.url || !sender.url.startsWith(browser.runtime.getURL(""))) {
      return Promise.resolve({ token: null });
    }
    return browser.storage.session.get(STORAGE_KEY).then(async (stored) => {
      const item = stored[STORAGE_KEY];
      await browser.storage.session.remove(STORAGE_KEY);
      if (!item || item.tabId !== tabId || !TOKEN_PATTERN.test(String(item.token || "")) || Date.now() - item.capturedAt > MAX_AGE_MS) {
        return { token: null };
      }
      return { token: item.token };
    });
  }

  return undefined;
});

browser.runtime.onStartup.addListener(() => {
  browser.storage.session.remove(STORAGE_KEY).catch(() => {});
});
