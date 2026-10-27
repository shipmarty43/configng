// SPDX-License-Identifier: GPL-3.0-or-later
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(`${__dirname}/h264.js`, 'utf8');
const nativeResult = {supported: true, smooth: true, powerEfficient: false};
const context = vm.createContext({
  MediaSource: {isTypeSupported(type) { assert.equal(this, context.MediaSource); return type !== 'invalid'; }},
  HTMLMediaElement: function () {},
  navigator: {mediaCapabilities: {decodingInfo(config) {
    assert.equal(this, context.navigator.mediaCapabilities);
    if (!config) return Promise.reject(new TypeError('missing config'));
    return Promise.resolve(nativeResult);
  }}}
});
context.HTMLMediaElement.prototype.canPlayType = function(type) { return type === 'invalid' ? '' : 'probably'; };
vm.runInContext(source, context);
(async () => {
  const media = new context.HTMLMediaElement();
  for (const codec of ['vp09.00.51.08', 'vp9', 'av01.0.08M.08', 'hvc1.1.6.L93.B0']) {
    const mime = `video/mp4; codecs="${codec}"`;
    assert.equal(context.MediaSource.isTypeSupported(mime), false);
    assert.equal(media.canPlayType(mime), '');
    assert.equal((await context.navigator.mediaCapabilities.decodingInfo({video: {contentType: mime}})).supported, false);
  }
  assert.equal(context.MediaSource.isTypeSupported('video/webm; codecs="vp8"'), false);
  for (const mime of ['video/mp4; codecs="avc1.640028"', 'audio/webm; codecs="opus"', 'audio/mp4; codecs="mp4a.40.2"']) {
    assert.equal(context.MediaSource.isTypeSupported(mime), true);
    assert.equal(media.canPlayType(mime), 'probably');
    assert.equal(await context.navigator.mediaCapabilities.decodingInfo({video: {contentType: mime}}), nativeResult);
  }
  assert.equal(context.MediaSource.isTypeSupported('invalid'), false);
  await assert.rejects(context.navigator.mediaCapabilities.decodingInfo(), TypeError);
  console.log('PASS: rejects unsupported video; preserves H.264, audio and native errors');
})();
