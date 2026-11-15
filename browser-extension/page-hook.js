(() => {
  'use strict';

  if (window.top !== window || location.origin !== 'https://accounts.firefox.com') return;

  const CHANNEL = 'foxyforvps:page-webchannel:v1';

  function forwardToExtension(event) {
    try {
      const detail = JSON.stringify(event.detail);
      if (!detail) return;
      window.postMessage({ channel: CHANNEL, direction: 'from-page', detail }, location.origin);
    } catch (_) {
      // Ignore unrelated/unserializable page events.
    }
  }

  window.addEventListener('WebChannelMessageToChrome', forwardToExtension);
  document.addEventListener('WebChannelMessageToChrome', forwardToExtension);

  window.addEventListener('message', event => {
    if (event.source !== window || event.origin !== location.origin) return;
    const data = event.data;
    if (!data || data.channel !== CHANNEL || data.direction !== 'to-page' || typeof data.detail !== 'string') return;
    let detail;
    try {
      detail = JSON.parse(data.detail);
    } catch (_) {
      return;
    }
    for (const target of [window, document]) {
      try {
        target.dispatchEvent(new CustomEvent('WebChannelMessageToContent', { detail }));
      } catch (_) {
        // Try the other target too; Firefox versions differ in event routing.
      }
    }
  });
  window.postMessage({ channel: CHANNEL, direction: 'hook-ready' }, location.origin);
})();
