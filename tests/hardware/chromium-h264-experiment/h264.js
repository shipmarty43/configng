// SPDX-License-Identifier: GPL-3.0-or-later
// Only codec negotiation is changed; no requests, page content or cookies are read.
(() => {
  "use strict";
  const blocked = type => typeof type === "string" &&
    (/^video\/webm(?:\s*;|$)/i.test(type) ||
     /\b(?:vp8|vp9|vp08|vp09|av01|hev1|hvc1)(?=[.,;"\s]|$)/i.test(type));
  for (const source of [globalThis.MediaSource, globalThis.ManagedMediaSource]) {
    if (source && typeof source.isTypeSupported === "function") {
      const original = source.isTypeSupported;
      source.isTypeSupported = function (type) {
        return blocked(type) ? false : Reflect.apply(original, this, arguments);
      };
    }
  }
  const originalPlay = HTMLMediaElement.prototype.canPlayType;
  HTMLMediaElement.prototype.canPlayType = function (type) {
    return blocked(type) ? "" : Reflect.apply(originalPlay, this, arguments);
  };
  const capabilities = globalThis.navigator?.mediaCapabilities;
  if (capabilities && typeof capabilities.decodingInfo === "function") {
    const original = capabilities.decodingInfo;
    capabilities.decodingInfo = function (config) {
      if (blocked(config?.video?.contentType)) {
        return Promise.resolve({supported: false, smooth: false, powerEfficient: false});
      }
      return Reflect.apply(original, this, arguments);
    };
  }
})();
