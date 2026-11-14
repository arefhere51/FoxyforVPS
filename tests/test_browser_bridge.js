const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

const root = path.join(__dirname, "..", "browser-helper");
const read = (name) => fs.readFileSync(path.join(root, name), "utf8");

async function main() {
  const pageListeners = {};
  const documentListeners = {};
  const posted = [];
  const fakeWindow = {
    addEventListener: (name, fn) => { pageListeners[name] = fn; },
    postMessage: (data, targetOrigin) => posted.push({ data, targetOrigin })
  };
  const fakeDocument = { addEventListener: (name, fn) => { documentListeners[name] = fn; } };
  vm.runInNewContext(read("page-hook.js"), {
    window: fakeWindow,
    document: fakeDocument,
    location: { hostname: "accounts.firefox.com", origin: "https://accounts.firefox.com" }
  });

  const token = "a".repeat(64);
  pageListeners.WebChannelMessageToChrome({ detail: {
    message: { command: "fxaccounts:login", data: { sessionToken: token } }
  } });
  assert.equal(posted.length, 1, "valid Firefox WebChannel login should be bridged");
  assert.equal(posted[0].data.token, token);
  assert.equal(posted[0].targetOrigin, "https://accounts.firefox.com");
  pageListeners.WebChannelMessageToChrome({ detail: {
    message: { command: "unrelated", data: { sessionToken: token } }
  } });
  pageListeners.WebChannelMessageToChrome({ detail: {
    message: { command: "fxaccounts:login", data: { sessionToken: "bad" } }
  } });
  assert.equal(posted.length, 1, "unrelated or malformed messages must be ignored");
  assert.ok(documentListeners.WebChannelMessageToChrome, "document event listener must be installed");

  const isolatedListeners = {};
  const isolatedWindow = { addEventListener: (name, fn) => { isolatedListeners[name] = fn; } };
  const relayed = [];
  vm.runInNewContext(read("content.js"), {
    window: isolatedWindow,
    browser: { runtime: { sendMessage: (value) => { relayed.push(value); return Promise.resolve(); } } }
  });
  isolatedListeners.message({ source: isolatedWindow, origin: "https://accounts.firefox.com", data: posted[0].data });
  assert.equal(relayed.length, 1, "valid same-window message should reach the extension background");
  assert.equal(relayed[0].token, token);
  isolatedListeners.message({ source: isolatedWindow, origin: "https://evil.example", data: posted[0].data });
  assert.equal(relayed.length, 1, "foreign origins must be ignored");

  const state = {};
  let backgroundListener;
  const runtimeBase = "moz-extension://foxyforvps-login-bridge@arefhere51/";
  const fakeBrowser = {
    runtime: {
      getURL: () => runtimeBase,
      onMessage: { addListener: (fn) => { backgroundListener = fn; } },
      onStartup: { addListener: () => {} }
    },
    storage: { session: {
      set: async (items) => Object.assign(state, items),
      get: async (key) => ({ [key]: state[key] }),
      remove: async (key) => { delete state[key]; }
    } }
  };
  vm.runInNewContext(read("background.js"), { browser: fakeBrowser, URL, Date, Number, String, Promise });
  const saved = await backgroundListener({ type: "foxy-capture-session", token }, { url: "https://accounts.firefox.com/settings", tab: { id: 42 } });
  assert.equal(saved.ok, true);
  const taken = await backgroundListener({ type: "foxy-take-session", tabId: 42 }, { url: `${runtimeBase}popup.html` });
  assert.equal(taken.token, token, "popup on the same active tab should consume the token");
  assert.equal(state.foxyforvpsCapturedSession, undefined, "token must be removed after consumption");

  console.log("Firefox WebChannel bridge mock tests passed.");
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
