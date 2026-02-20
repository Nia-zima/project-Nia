const { getBot, isConnected } = require("./bot");
const { goals } = require("mineflayer-pathfinder");

/**
 * アクションを実行
 * @param {string} action - アクション名
 * @param {object} params - パラメータ
 * @returns {Promise<{success: boolean, result?: string, error?: string}>}
 */
async function executeAction(action, params = {}) {
  const bot = getBot();
  if (!bot || !isConnected()) {
    return { success: false, error: "Bot not connected" };
  }

  const handlers = {
    move_to: _moveTo,
    mine_block: _mineBlock,
    place_block: _placeBlock,
    craft: _craft,
    attack: _attack,
    chat: _chat,
    look_at: _lookAt,
    use_item: _useItem,
    equip: _equip,
    drop_item: _dropItem,
    stop: _stop,
  };

  const handler = handlers[action];
  if (!handler) {
    return { success: false, error: `Unknown action: ${action}` };
  }

  try {
    const result = await handler(bot, params);
    return { success: true, result };
  } catch (err) {
    return { success: false, error: err.message };
  }
}

async function _moveTo(bot, { x, y, z }) {
  if (x === undefined || z === undefined) {
    throw new Error("x and z are required");
  }
  const targetY = y !== undefined ? y : bot.entity.position.y;
  const goal = new goals.GoalNear(x, targetY, z, 1);
  await bot.pathfinder.goto(goal);
  return `Moved to (${Math.round(x)}, ${Math.round(targetY)}, ${Math.round(z)})`;
}

async function _mineBlock(bot, { x, y, z }) {
  if (x === undefined || y === undefined || z === undefined) {
    throw new Error("x, y, z are required");
  }
  const block = bot.blockAt(bot.entity.position.offset(0, 0, 0));
  const target = bot.blockAt({ x, y, z });
  if (!target || target.name === "air") {
    throw new Error("No block at target position");
  }
  await bot.dig(target);
  return `Mined ${target.name} at (${x}, ${y}, ${z})`;
}

async function _placeBlock(bot, { x, y, z, item }) {
  if (x === undefined || y === undefined || z === undefined) {
    throw new Error("x, y, z are required");
  }
  if (item) {
    const invItem = bot.inventory.items().find((i) => i.name === item);
    if (invItem) {
      await bot.equip(invItem, "hand");
    }
  }
  const refBlock = bot.blockAt({ x, y: y - 1, z });
  if (!refBlock) throw new Error("No reference block found");
  await bot.placeBlock(refBlock, { x: 0, y: 1, z: 0 });
  return `Placed block at (${x}, ${y}, ${z})`;
}

async function _craft(bot, { item, count = 1 }) {
  if (!item) throw new Error("item is required");
  const mcData = require("minecraft-data")(bot.version);
  const recipe = bot.recipesFor(mcData.itemsByName[item]?.id)?.[0];
  if (!recipe) throw new Error(`No recipe found for ${item}`);
  await bot.craft(recipe, count);
  return `Crafted ${item} x${count}`;
}

async function _attack(bot, { entity_name }) {
  if (!entity_name) throw new Error("entity_name is required");
  const target = Object.values(bot.entities).find((e) => {
    const name = e.username || e.displayName || e.name || "";
    return name.toLowerCase() === entity_name.toLowerCase();
  });
  if (!target) throw new Error(`Entity "${entity_name}" not found nearby`);
  await bot.attack(target);
  return `Attacked ${entity_name}`;
}

async function _chat(bot, { message }) {
  if (!message) throw new Error("message is required");
  bot.chat(message);
  return `Sent: ${message}`;
}

async function _lookAt(bot, { x, y, z }) {
  if (x === undefined || y === undefined || z === undefined) {
    throw new Error("x, y, z are required");
  }
  await bot.lookAt({ x, y, z });
  return `Looking at (${x}, ${y}, ${z})`;
}

async function _useItem(bot) {
  bot.activateItem();
  return "Used item in hand";
}

async function _equip(bot, { item, destination = "hand" }) {
  if (!item) throw new Error("item is required");
  const invItem = bot.inventory.items().find((i) => i.name === item);
  if (!invItem) throw new Error(`Item "${item}" not in inventory`);
  await bot.equip(invItem, destination);
  return `Equipped ${item} to ${destination}`;
}

async function _dropItem(bot, { item, count }) {
  if (!item) throw new Error("item is required");
  const invItem = bot.inventory.items().find((i) => i.name === item);
  if (!invItem) throw new Error(`Item "${item}" not in inventory`);
  await bot.tossStack(invItem);
  return `Dropped ${item}`;
}

async function _stop(bot) {
  bot.pathfinder.stop();
  return "Stopped all movement";
}

module.exports = { executeAction };
