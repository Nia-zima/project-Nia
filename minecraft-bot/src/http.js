const express = require("express");
const { getState } = require("./state");
const { executeAction } = require("./actions");
const { isConnected, connect, disconnect } = require("./bot");
const { executeCode } = require("./sandbox");
const { executeSkill, saveSkill, listSkills } = require("./skill_manager");

/**
 * Express HTTP サーバーを作成
 */
function createHttpServer() {
  const app = express();
  app.use(express.json());

  // ヘルスチェック
  app.get("/health", (_req, res) => {
    res.json({
      ok: true,
      connected: isConnected(),
      uptime: process.uptime(),
    });
  });

  // ゲーム状態取得
  app.get("/state", (_req, res) => {
    res.json(getState());
  });

  // アクション実行
  app.post("/action", async (req, res) => {
    const { action, params } = req.body;
    if (!action) {
      return res.status(400).json({ success: false, error: "action is required" });
    }
    const result = await executeAction(action, params || {});
    res.json(result);
  });

  // サーバーに接続
  app.post("/connect", (req, res) => {
    const { host, port, username, version } = req.body || {};
    const result = connect({ host, port, username, version });
    res.json(result);
  });

  // 切断
  app.post("/disconnect", (_req, res) => {
    const result = disconnect();
    res.json(result);
  });

  // === Voyager スキルシステム ===

  // コード実行（サンドボックス）
  app.post("/execute_code", async (req, res) => {
    const { code, timeout } = req.body;
    if (!code) {
      return res.status(400).json({ success: false, error: "code is required" });
    }
    const result = await executeCode(code, { timeout });
    res.json(result);
  });

  // スキル実行
  app.post("/execute_skill", async (req, res) => {
    const { name, args } = req.body;
    if (!name) {
      return res.status(400).json({ success: false, error: "name is required" });
    }
    const result = await executeSkill(name, args || {});
    res.json(result);
  });

  // スキル一覧
  app.get("/skills", (_req, res) => {
    res.json({ skills: listSkills() });
  });

  // スキル保存
  app.post("/save_skill", (req, res) => {
    const { name, code, description } = req.body;
    if (!name || !code) {
      return res.status(400).json({ ok: false, error: "name and code are required" });
    }
    const result = saveSkill(name, code, description || "");
    res.json(result);
  });

  return app;
}

module.exports = { createHttpServer };
