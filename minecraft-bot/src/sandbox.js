const vm = require("vm");
const { getBot, isConnected } = require("./bot");
const { goals } = require("mineflayer-pathfinder");

const DEFAULT_TIMEOUT_MS = 30_000;

/**
 * LLM 生成の JS コードを安全に実行するサンドボックス
 *
 * 注入されるグローバル:
 *   bot, goals, Vec3, mcData, sleep, console.log
 *
 * 遮断:
 *   require, process, fs, child_process, eval (native), Function
 */
async function executeCode(code, { timeout = DEFAULT_TIMEOUT_MS } = {}) {
  const bot = getBot();
  if (!bot || !isConnected()) {
    return { success: false, error: "Bot not connected", logs: [] };
  }

  const mcData = require("minecraft-data")(bot.version);
  const Vec3 = require("vec3");

  const logs = [];

  // 安全なグローバルのみ注入
  const sandbox = {
    bot,
    goals,
    Vec3,
    mcData,
    sleep: (ms) => new Promise((r) => setTimeout(r, Math.min(ms, 10_000))),
    console: {
      log: (...args) => {
        const line = args.map((a) => (typeof a === "object" ? JSON.stringify(a) : String(a))).join(" ");
        logs.push(line);
        if (logs.length > 100) logs.shift();
      },
    },
    setTimeout,
    clearTimeout,
    Promise,
    Math,
    Date,
    JSON,
    Array,
    Object,
    String,
    Number,
    Boolean,
    Map,
    Set,
    Error,
    TypeError,
    RangeError,
  };

  // async コードをラップ
  const wrappedCode = `
    (async () => {
      ${code}
    })()
  `;

  try {
    const script = new vm.Script(wrappedCode, {
      filename: "nia-skill.js",
      timeout: 5000, // 同期部分のタイムアウト（5s）
    });

    const context = vm.createContext(sandbox);

    // 実行（async なので Promise が返る）
    const resultPromise = script.runInContext(context);

    // 全体タイムアウト（async 部分含む）
    const result = await Promise.race([
      resultPromise,
      new Promise((_, reject) =>
        setTimeout(() => reject(new Error(`Execution timed out (${timeout}ms)`)), timeout)
      ),
    ]);

    return {
      success: true,
      result: _serialize(result),
      logs,
    };
  } catch (err) {
    return {
      success: false,
      error: err.message || String(err),
      logs,
    };
  }
}

/**
 * 結果をシリアライズ可能な形に変換
 */
function _serialize(value) {
  if (value === undefined || value === null) return value;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return value;
  }
  try {
    return JSON.parse(JSON.stringify(value));
  } catch {
    return String(value);
  }
}

module.exports = { executeCode };
