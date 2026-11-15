(() => {
  'use strict';

  if (window.top !== window || location.origin !== 'https://accounts.firefox.com') return;

  const TOKEN_RE = /^[0-9a-f]{64}$/i;
  const NONCE_RE = /^[A-Za-z0-9_-]{43}$/;
  const PAGE_CHANNEL = 'foxyforvps:page-webchannel:v1';
  let bridge = null;
  let pendingSession = null;
  let delivering = false;
  let sentTokenDigests = new Set();

  function isAllowedPanelOrigin(origin) {
    try {
      const url = new URL(origin);
      if (url.protocol === 'https:') return true;
      if (url.protocol !== 'http:') return false;
      return url.hostname === 'localhost' || url.hostname === '127.0.0.1' || url.hostname === '[::1]';
    } catch (_) {
      return false;
    }
  }

  async function deliverPendingSession() {
    if (!bridge || !pendingSession || delivering || !window.opener) return;
    delivering = true;
    const session = pendingSession;
    pendingSession = null;
    try {
      let fingerprint = '';
      try {
        const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(session.token));
        fingerprint = [...new Uint8Array(digest)].map(value => value.toString(16).padStart(2, '0')).join('');
      } catch (_) {
        // Do not retain the raw session only to deduplicate a message.
      }
      if (fingerprint && sentTokenDigests.has(fingerprint)) return;
      const accepted = window.confirm(
        `FoxyforVPS می‌خواهد نشست موقت Firefox را فقط به پنل زیر بفرستد:\n\n${bridge.origin}\n\nگذرواژه یا کد تأیید ارسال نمی‌شود. اجازه می‌دهی؟`
      );
      if (!accepted) return;
      window.opener.postMessage({
        type: 'foxyforvps:fxa-session',
        nonce: bridge.nonce,
        email: session.email,
        sessionToken: session.token,
      }, bridge.origin);
      if (fingerprint) {
        sentTokenDigests.add(fingerprint);
        if (sentTokenDigests.size > 4) sentTokenDigests = new Set([...sentTokenDigests].slice(-4));
      }
    } catch (_) {
      pendingSession = null;
    } finally {
      session.token = '';
      delivering = false;
      if (pendingSession) queueMicrotask(deliverPendingSession);
    }
  }

  window.addEventListener('message', event => {
    if (event.source !== window.opener || !event.data || event.data.type !== 'foxyforvps:bridge-init') return;
    const nonce = event.data.nonce;
    if (typeof nonce !== 'string' || !NONCE_RE.test(nonce) || !isAllowedPanelOrigin(event.origin)) return;
    if (bridge && (bridge.nonce !== nonce || bridge.origin !== event.origin)) return;
    bridge = { nonce, origin: event.origin };
    try {
      window.opener.postMessage({ type: 'foxyforvps:bridge-ready', nonce }, bridge.origin);
      deliverPendingSession();
    } catch (_) {
      bridge = null;
    }
  });

  function sendWebChannelReply(id, messageId, command, data) {
    const detail = JSON.stringify({ id, message: { messageId, command, data } });
    window.postMessage({ channel: PAGE_CHANNEL, direction: 'to-page', detail }, location.origin);
  }

  function handlePageMessage(event) {
    if (event.source !== window || event.origin !== location.origin) return;
    const envelope = event.data;
    if (!envelope || envelope.channel !== PAGE_CHANNEL || envelope.direction !== 'from-page' || typeof envelope.detail !== 'string') return;
    let detail;
    try { detail = JSON.parse(envelope.detail); } catch (_) { return; }
    if (!detail || typeof detail.id !== 'string' || !detail.message || typeof detail.message !== 'object') return;

    const message = detail.message;
    const command = message.command;
    if (command === 'fxaccounts:fxa_status') {
      sendWebChannelReply(detail.id, message.messageId, command, {
        capabilities: {},
        signedInUser: null,
      });
      return;
    }
    if (command === 'fxaccounts:can_link_account') {
      sendWebChannelReply(detail.id, message.messageId, command, { ok: true });
      return;
    }
    if (command !== 'fxaccounts:login' && command !== 'fxaccounts:oauth_login') return;

    const data = message.data;
    if (!data || typeof data !== 'object') return;
    const token = data.sessionToken || data.token;
    if (typeof token !== 'string' || !TOKEN_RE.test(token)) return;
    const email = typeof data.email === 'string' ? data.email.slice(0, 254) : '';
    pendingSession = { email, token };
    deliverPendingSession();
  }

  window.addEventListener('message', handlePageMessage);
})();
