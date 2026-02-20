const mineflayer = require("mineflayer");
const { pathfinder, Movements, goals } = require("mineflayer-pathfinder");

let bot = null;
let reconnectTimer = null;

/**
 * 現在の Bot インスタンスを返す
 */
function getBot() {
  return bot;
}

/**
 * Bot が接続中かどうか
 */
function isConnected() {
  return bot !== null && bot.entity !== undefined;
}

/**
 * Minecraft サーバーに接続
 */
function connect(options = {}) {
  if (bot) {
    disconnect();
  }

  const host = options.host || process.env.MC_HOST || "localhost";
  const port = parseInt(options.port || process.env.MC_PORT || "25565", 10);
  const username = options.username || process.env.MC_USERNAME || "Nia";
  const version = options.version || process.env.MC_VERSION || "1.20.4";

  console.log(`[BOT] Connecting to ${host}:${port} as ${username} (v${version})`);

  bot = mineflayer.createBot({
    host,
    port,
    username,
    version,
    hideErrors: false,
  });

  bot.loadPlugin(pathfinder);

  bot.once("spawn", () => {
    console.log(`[BOT] Spawned at ${_posStr(bot.entity.position)}`);
    const mcData = require("minecraft-data")(bot.version);
    const movements = new Movements(bot, mcData);
    movements.allowSprinting = true;
    bot.pathfinder.setMovements(movements);
  });

  bot.on("error", (err) => {
    console.error("[BOT] Error:", err.message);
  });

  bot.on("kicked", (reason) => {
    console.warn("[BOT] Kicked:", reason);
    bot = null;
    _scheduleReconnect(options);
  });

  bot.on("end", (reason) => {
    console.log("[BOT] Disconnected:", reason);
    bot = null;
    _scheduleReconnect(options);
  });

  return { ok: true, host, port, username, version };
}

/**
 * Bot を切断
 */
function disconnect() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  if (bot) {
    bot.removeAllListeners();
    bot.quit();
    bot = null;
    console.log("[BOT] Disconnected (manual)");
  }
  return { ok: true };
}

/**
 * 再接続スケジュール (5秒後)
 */
function _scheduleReconnect(options) {
  if (reconnectTimer) return;
  console.log("[BOT] Reconnecting in 5s...");
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect(options);
  }, 5000);
}

function _posStr(pos) {
  if (!pos) return "unknown";
  return `(${Math.round(pos.x)}, ${Math.round(pos.y)}, ${Math.round(pos.z)})`;
}

module.exports = { getBot, isConnected, connect, disconnect };
