const { WebSocketServer } = require("ws");
const { onEvent } = require("./events");

let wss = null;

/**
 * WebSocket サーバーを起動してイベントをブロードキャスト
 */
function startWsServer(port) {
  wss = new WebSocketServer({ port });

  console.log(`[WS] Server listening on ws://localhost:${port}`);

  wss.on("connection", (ws) => {
    console.log("[WS] Client connected");

    ws.on("message", (data) => {
      try {
        const msg = JSON.parse(data);
        if (msg.type === "ping") {
          ws.send(JSON.stringify({ type: "pong", ts: Date.now() }));
        }
      } catch {
        // ignore invalid messages
      }
    });

    ws.on("close", () => {
      console.log("[WS] Client disconnected");
    });
  });

  // Bot イベントを全クライアントにブロードキャスト
  onEvent((event) => {
    const payload = JSON.stringify(event);
    for (const client of wss.clients) {
      if (client.readyState === 1) {
        client.send(payload);
      }
    }
  });

  return wss;
}

function stopWsServer() {
  if (wss) {
    wss.close();
    wss = null;
  }
}

module.exports = { startWsServer, stopWsServer };
