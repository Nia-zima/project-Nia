const { getBot } = require("./bot");

/** @type {Set<function>} */
const listeners = new Set();

/**
 * イベントリスナーを登録
 * @param {function} callback - (event: {type, data, ts}) => void
 */
function onEvent(callback) {
  listeners.add(callback);
  return () => listeners.delete(callback);
}

/**
 * Bot のイベントを購読開始
 * connect() の後に呼ぶ
 */
function attachBotEvents(bot) {
  if (!bot) return;

  bot.on("health", () => {
    _emit("health_change", {
      health: bot.health,
      food: bot.food,
    });
  });

  bot.on("entityHurt", (entity) => {
    if (entity === bot.entity) {
      _emit("damage", { health: bot.health });
    }
  });

  bot.on("death", () => {
    _emit("death", { message: "Bot died" });
  });

  bot.on("respawn", () => {
    _emit("respawn", {
      position: _posObj(bot.entity?.position),
    });
  });

  bot.on("chat", (username, message) => {
    if (username === bot.username) return;
    _emit("chat", { username, message });
  });

  bot.on("entitySpawn", (entity) => {
    if (entity === bot.entity) return;
    const dist = bot.entity?.position?.distanceTo(entity.position);
    if (dist && dist < 16) {
      _emit("entity_spawn", {
        name: entity.username || entity.displayName || entity.name || "unknown",
        type: entity.type,
        distance: Math.round(dist * 10) / 10,
      });
    }
  });

  bot.on("entityGone", (entity) => {
    _emit("entity_gone", {
      name: entity.username || entity.displayName || entity.name || "unknown",
      type: entity.type,
    });
  });

  bot.on("playerCollect", (collector, collected) => {
    if (collector === bot.entity) {
      _emit("collect", {
        item: collected.displayName || collected.name || "item",
      });
    }
  });

  bot.on("rain", () => {
    _emit("weather", { isRaining: bot.isRaining });
  });

  bot.on("time", () => {
    const t = bot.time?.timeOfDay;
    // 日の出・日没のみ通知
    if (t === 0) _emit("time_change", { period: "sunrise" });
    else if (t === 12000) _emit("time_change", { period: "sunset" });
  });
}

function _emit(type, data) {
  const event = { type, data, ts: Date.now() };
  for (const cb of listeners) {
    try {
      cb(event);
    } catch (err) {
      console.error("[EVENTS] Listener error:", err.message);
    }
  }
}

function _posObj(pos) {
  if (!pos) return null;
  return {
    x: Math.round(pos.x),
    y: Math.round(pos.y),
    z: Math.round(pos.z),
  };
}

module.exports = { onEvent, attachBotEvents };
