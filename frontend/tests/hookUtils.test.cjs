const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");

function loadTsModule(filePath) {
  const source = fs.readFileSync(filePath, "utf8");
  const transpiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
    },
    fileName: filePath,
  });

  const module = { exports: {} };
  const wrapper = new Function(
    "exports",
    "require",
    "module",
    "__filename",
    "__dirname",
    transpiled.outputText,
  );
  wrapper(module.exports, require, module, filePath, path.dirname(filePath));
  return module.exports;
}

function test(name, fn) {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (error) {
    console.error(`FAIL ${name}`);
    throw error;
  }
}

const voiceUtils = loadTsModule(path.join(__dirname, "..", "hooks", "voiceModeUtils.ts"));
const audioUtils = loadTsModule(path.join(__dirname, "..", "hooks", "audioPlaybackUtils.ts"));

test("toNum returns fallback for invalid input", () => {
  assert.equal(voiceUtils.toNum("abc", 5), 5);
  assert.equal(voiceUtils.toNum(undefined, 3), 3);
  assert.equal(voiceUtils.toNum("1.25", 0), 1.25);
});

test("buildVoiceWsUrl uses explicit base when provided", () => {
  const actual = voiceUtils.buildVoiceWsUrl({
    sessionId: "sid-1",
    clientId: "client A",
    explicitBase: "wss://voice.example.com/",
    protocol: "https:",
    hostname: "unused.local",
    backendPort: "9999",
  });
  assert.equal(actual, "wss://voice.example.com/voice/ws?session_id=sid-1&client_id=client%20A");
});

test("buildVoiceWsUrl falls back to protocol/hostname/port", () => {
  const actual = voiceUtils.buildVoiceWsUrl({
    sessionId: "sid",
    clientId: "cid",
    protocol: "https:",
    hostname: "app.local",
    backendPort: "9000",
  });
  assert.equal(actual, "wss://app.local:9000/api/voice/ws?session_id=sid&client_id=cid");
});

test("shouldSkipAutoSend handles empty and duplicate window", () => {
  assert.equal(voiceUtils.shouldSkipAutoSend("", "prev", 100), true);
  assert.equal(voiceUtils.shouldSkipAutoSend("hello", "hello", 3999), true);
  assert.equal(voiceUtils.shouldSkipAutoSend("hello", "hello", 4000), false);
  assert.equal(voiceUtils.shouldSkipAutoSend("new", "old", 50), false);
});

test("normalizeAutoSendText trims safely", () => {
  assert.equal(voiceUtils.normalizeAutoSendText("  text  "), "text");
  assert.equal(voiceUtils.normalizeAutoSendText(""), "");
});

test("quantizeVolume clamps and rounds to 2 decimals", () => {
  assert.equal(audioUtils.quantizeVolume(-0.1), 0);
  assert.equal(audioUtils.quantizeVolume(1.2), 1);
  assert.equal(audioUtils.quantizeVolume(0.126), 0.13);
});

test("shouldEmitVolume enforces throttle rule", () => {
  assert.equal(audioUtils.shouldEmitVolume(1000, 950, 0.5, 0.49, false), false);
  assert.equal(audioUtils.shouldEmitVolume(1020, 950, 0.5, 0.49, false), true);
  assert.equal(audioUtils.shouldEmitVolume(1000, 990, 0.6, 0.5, false), true);
  assert.equal(audioUtils.shouldEmitVolume(1000, 999, 0.5, 0.5, true), true);
});
