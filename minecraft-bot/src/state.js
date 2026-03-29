const { getBot, isConnected } = require("./bot");

/**
 * 現在のゲーム状態スナップショットを生成
 */
function getState() {
  const bot = getBot();
  if (!bot || !isConnected()) {
    return { connected: false };
  }

  return {
    connected: true,
    position: _getPosition(bot),
    health: bot.health,
    food: bot.food,
    experience: {
      level: bot.experience?.level || 0,
      points: bot.experience?.points || 0,
    },
    inventory: _getInventory(bot),
    nearbyEntities: _getNearbyEntities(bot, 16),
    nearbyBlocks: _getNotableBlocks(bot, 8),
    time: _getTime(bot),
    biome: _getBiome(bot),
  };
}

function _getPosition(bot) {
  const pos = bot.entity?.position;
  if (!pos) return null;
  return {
    x: Math.round(pos.x * 10) / 10,
    y: Math.round(pos.y * 10) / 10,
    z: Math.round(pos.z * 10) / 10,
    yaw: Math.round((bot.entity.yaw * 180) / Math.PI),
    pitch: Math.round((bot.entity.pitch * 180) / Math.PI),
  };
}

function _getInventory(bot) {
  const items = [];
  for (const item of bot.inventory.items()) {
    items.push({
      name: item.name,
      count: item.count,
      slot: item.slot,
    });
  }
  return items;
}

function _getNearbyEntities(bot, radius) {
  const entities = [];
  for (const entity of Object.values(bot.entities)) {
    if (entity === bot.entity) continue;
    const dist = bot.entity.position.distanceTo(entity.position);
    if (dist > radius) continue;

    entities.push({
      name: entity.username || entity.displayName || entity.name || "unknown",
      type: entity.type,
      distance: Math.round(dist * 10) / 10,
      position: {
        x: Math.round(entity.position.x),
        y: Math.round(entity.position.y),
        z: Math.round(entity.position.z),
      },
    });
  }
  // 近い順にソート
  entities.sort((a, b) => a.distance - b.distance);
  return entities.slice(0, 20);
}

function _getNotableBlocks(bot, radius) {
  const notable = new Set([
    "chest",
    "crafting_table",
    "furnace",
    "anvil",
    "enchanting_table",
    "brewing_stand",
    "bed",
    "diamond_ore",
    "deepslate_diamond_ore",
    "iron_ore",
    "deepslate_iron_ore",
    "gold_ore",
    "deepslate_gold_ore",
    "lapis_ore",
    "redstone_ore",
    "emerald_ore",
    "spawner",
    "portal",
    "nether_portal",
    "end_portal",
  ]);

  const found = [];
  const pos = bot.entity.position;

  for (let dx = -radius; dx <= radius; dx++) {
    for (let dy = -radius; dy <= radius; dy++) {
      for (let dz = -radius; dz <= radius; dz++) {
        const block = bot.blockAt(pos.offset(dx, dy, dz));
        if (block && notable.has(block.name)) {
          found.push({
            name: block.name,
            position: {
              x: block.position.x,
              y: block.position.y,
              z: block.position.z,
            },
          });
        }
      }
    }
  }
  return found.slice(0, 10);
}

function _getTime(bot) {
  const timeOfDay = bot.time?.timeOfDay;
  if (timeOfDay === undefined) return { period: "unknown", ticks: 0 };

  let period;
  if (timeOfDay < 6000) period = "morning";
  else if (timeOfDay < 12000) period = "day";
  else if (timeOfDay < 13000) period = "sunset";
  else if (timeOfDay < 23000) period = "night";
  else period = "sunrise";

  return {
    period,
    ticks: timeOfDay,
    isRaining: bot.isRaining || false,
  };
}

function _getBiome(bot) {
  try {
    const pos = bot.entity.position;
    const block = bot.blockAt(pos);
    return block?.biome?.name || "unknown";
  } catch {
    return "unknown";
  }
}

module.exports = { getState };
