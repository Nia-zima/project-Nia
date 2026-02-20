const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

const SKILLS_DIR = path.join(__dirname, "..", "skills");

/** @type {Map<string, {execute: Function, description: string, hash: string}>} */
const loadedSkills = new Map();

/**
 * skills/ ディレクトリを作成（なければ）
 */
function ensureSkillsDir() {
  if (!fs.existsSync(SKILLS_DIR)) {
    fs.mkdirSync(SKILLS_DIR, { recursive: true });
    console.log("[SKILLS] Created skills/ directory");
  }
}

/**
 * skills/ からすべてのスキルを読み込み
 */
function loadSkills() {
  ensureSkillsDir();
  loadedSkills.clear();

  const files = fs.readdirSync(SKILLS_DIR).filter((f) => f.endsWith(".js"));
  for (const file of files) {
    const name = path.basename(file, ".js");
    try {
      const fullPath = path.join(SKILLS_DIR, file);
      // キャッシュを無効化して再読み込み
      delete require.cache[require.resolve(fullPath)];
      const mod = require(fullPath);

      if (typeof mod.execute !== "function") {
        console.warn(`[SKILLS] ${file}: missing execute() function, skipped`);
        continue;
      }

      const code = fs.readFileSync(fullPath, "utf-8");
      const hash = _hash(code);

      loadedSkills.set(name, {
        execute: mod.execute,
        description: mod.description || "",
        hash,
      });
      console.log(`[SKILLS] Loaded: ${name} - ${mod.description || "(no description)"}`);
    } catch (err) {
      console.error(`[SKILLS] Failed to load ${file}:`, err.message);
    }
  }

  console.log(`[SKILLS] ${loadedSkills.size} skill(s) loaded`);
  return loadedSkills.size;
}

/**
 * スキルを実行
 */
async function executeSkill(name, args = {}) {
  const skill = loadedSkills.get(name);
  if (!skill) {
    return { success: false, error: `Skill "${name}" not found` };
  }

  const { getBot, isConnected } = require("./bot");
  const bot = getBot();
  if (!bot || !isConnected()) {
    return { success: false, error: "Bot not connected" };
  }

  try {
    const result = await skill.execute(bot, args);
    return { success: true, result, skill: name };
  } catch (err) {
    return { success: false, error: err.message, skill: name };
  }
}

/**
 * 新しいスキルを保存
 * @param {string} name - スキル名（ファイル名に使用）
 * @param {string} code - JS コード
 * @param {string} description - 説明文
 * @returns {{ok: boolean, path?: string, hash?: string, error?: string}}
 */
function saveSkill(name, code, description = "") {
  ensureSkillsDir();

  // 名前の検証（英数字、アンダースコア、ハイフンのみ）
  if (!/^[a-zA-Z0-9_-]+$/.test(name)) {
    return { ok: false, error: "Invalid skill name (use alphanumeric, _, -)" };
  }

  const hash = _hash(code);

  // 重複チェック
  const existing = loadedSkills.get(name);
  if (existing && existing.hash === hash) {
    return { ok: true, path: _skillPath(name), hash, message: "Already exists (same hash)" };
  }

  const filePath = _skillPath(name);
  fs.writeFileSync(filePath, code, "utf-8");
  console.log(`[SKILLS] Saved: ${name} (${hash.slice(0, 8)})`);

  // リロード
  try {
    delete require.cache[require.resolve(filePath)];
    const mod = require(filePath);
    if (typeof mod.execute === "function") {
      loadedSkills.set(name, {
        execute: mod.execute,
        description: mod.description || description,
        hash,
      });
    }
  } catch (err) {
    console.warn(`[SKILLS] Saved but failed to load ${name}:`, err.message);
  }

  return { ok: true, path: filePath, hash };
}

/**
 * スキル一覧を返す
 */
function listSkills() {
  const skills = [];
  for (const [name, skill] of loadedSkills) {
    skills.push({
      name,
      description: skill.description,
      hash: skill.hash,
    });
  }
  return skills;
}

/**
 * スキルが存在するか
 */
function hasSkill(name) {
  return loadedSkills.has(name);
}

function _skillPath(name) {
  return path.join(SKILLS_DIR, `${name}.js`);
}

function _hash(code) {
  return crypto.createHash("sha256").update(code).digest("hex");
}

module.exports = {
  ensureSkillsDir,
  loadSkills,
  executeSkill,
  saveSkill,
  listSkills,
  hasSkill,
};
