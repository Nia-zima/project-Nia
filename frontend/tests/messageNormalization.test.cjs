const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");

function loadMessageNormalization() {
  const filePath = path.join(__dirname, "..", "components", "chat", "messageNormalization.ts");
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

const {
  normalizeContent,
  extractSpeech,
  normalizeHistoryMessage,
  isLikelyDuplicateAppend,
  dedupeAdjacentDuplicateParagraphs,
} = loadMessageNormalization();

function test(name, fn) {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (error) {
    console.error(`FAIL ${name}`);
    throw error;
  }
}

test("normalizeContent keeps plain string", () => {
  assert.equal(normalizeContent("hello"), "hello");
});

test("normalizeContent handles multipart content", () => {
  const actual = normalizeContent([
    { type: "text", text: "a" },
    { type: "input_text", text: "b" },
    { type: "image_url", image_url: { url: "https://example.com/img.png" } },
  ]);
  assert.equal(actual, "ab\n[画像: https://example.com/img.png]");
});

test("extractSpeech removes trailing metadata block", () => {
  const actual = extractSpeech("line1\nline2\n[[meta]]");
  assert.equal(actual, "line1\nline2");
});

test("extractSpeech removes leading metadata lines", () => {
  const actual = extractSpeech("[[tag]]\n[[score:0.2]]\nfinal speech");
  assert.equal(actual, "final speech");
});

test("normalizeHistoryMessage maps assistant role and drops data URLs", () => {
  const msg = normalizeHistoryMessage({
    role: "assistant",
    content: [
      { type: "text", text: "hello" },
      { type: "image_url", image_url: { url: "data:image/png;base64,AAAA" } },
    ],
  });
  assert.equal(msg.role, "ai");
  assert.equal(msg.content, "hello");
  assert.equal(msg.type, "text");
  assert.equal(msg.image, undefined);
});

test("isLikelyDuplicateAppend detects long duplicate suffix", () => {
  const line = "this is a long line with enough length";
  assert.equal(isLikelyDuplicateAppend(`${line}\n${line}`, line), true);
});

test("dedupeAdjacentDuplicateParagraphs removes adjacent duplicates", () => {
  const text = "alpha\nalpha\nbeta\nbeta";
  assert.equal(dedupeAdjacentDuplicateParagraphs(text), "alpha\nbeta");
});

test("dedupeAdjacentDuplicateParagraphs removes repeated halves", () => {
  const text = "alpha\nbeta\nalpha\nbeta";
  assert.equal(dedupeAdjacentDuplicateParagraphs(text), "alpha\nbeta");
});
