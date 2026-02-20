require("dotenv").config();

const { connect, getBot } = require("./bot");
const { attachBotEvents } = require("./events");
const { createHttpServer } = require("./http");
const { startWsServer } = require("./ws");
const { ensureSkillsDir, loadSkills } = require("./skill_manager");

const HTTP_PORT = parseInt(process.env.BOT_HTTP_PORT || "3100", 10);
const WS_PORT = parseInt(process.env.BOT_WS_PORT || "3101", 10);

// スキルディレクトリ確保 + 既存スキル読み込み
ensureSkillsDir();
loadSkills();

// HTTP サーバー起動
const app = createHttpServer();
app.listen(HTTP_PORT, () => {
  console.log(`[HTTP] Server listening on http://localhost:${HTTP_PORT}`);
});

// WebSocket サーバー起動
startWsServer(WS_PORT);

// Bot 接続
const result = connect();
console.log("[INIT] Bot connect:", result);

// spawn 後にイベントリスナーを接続
const checkBot = setInterval(() => {
  const bot = getBot();
  if (bot && bot.entity) {
    clearInterval(checkBot);
    attachBotEvents(bot);
    console.log("[INIT] Event listeners attached");
  }
}, 500);

// Graceful shutdown
process.on("SIGINT", () => {
  console.log("\n[SHUTDOWN] Cleaning up...");
  const { disconnect } = require("./bot");
  const { stopWsServer } = require("./ws");
  disconnect();
  stopWsServer();
  process.exit(0);
});
