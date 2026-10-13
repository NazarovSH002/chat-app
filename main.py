from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import json

app = FastAPI()

class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[WebSocket, str] = {}
        self.message_history: list[dict] = []

    async def connect(self, websocket: WebSocket, client_name: str):
        await websocket.accept()
        self.active_connections[websocket] = client_name
        
        # Отправляем историю новому пользователю
        await websocket.send_text(json.dumps({
            "type": "history",
            "messages": self.message_history
        }))
        
        await self.broadcast_online_users()

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            del self.active_connections[websocket]

    async def broadcast(self, data: dict):
        action_type = data.get("type")
        if action_type in ["message", "media", "system"]:
            # Присваиваем уникальный ID сообщению для возможности удаления
            data["id"] = len(self.message_history)
            self.message_history.append(data)
            if len(self.message_history) > 50:
                self.message_history.pop(0)

        message = json.dumps(data)
        for connection in self.active_connections.keys():
            try:
                await connection.send_text(message)
            except Exception:
                pass

    async def delete_message(self, msg_id: int):
        # Удаляем сообщение из истории сервера
        self.message_history = [m for m in self.message_history if m.get("id") != msg_id]
        # Рассылаем сигнал удаления всем участникам чата
        data = json.dumps({"type": "delete", "id": msg_id})
        for connection in self.active_connections.keys():
            try:
                await connection.send_text(data)
            except Exception:
                pass

    async def broadcast_online_users(self):
        users = list(self.active_connections.values())
        online_data = json.dumps({"type": "online_list", "users": users})
        for connection in self.active_connections.keys():
            try:
                await connection.send_text(online_data)
            except Exception:
                pass

manager = ConnectionManager()

html = """
<!DOCTYPE html>
<html lang="ru">
    <head>
        <meta charset="UTF-8"/>
        <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
        <title>Чат с удалением сообщений</title>
        <style>
            body { font-family: Arial, sans-serif; background: #f4f7f6; margin: 0; padding: 20px; display: flex; justify-content: center; }
            .chat-container { width: 100%; max-width: 800px; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 4px 10px rgba(0,0,0,0.1); display: flex; gap: 20px; }
            .main-chat { flex: 2; display: flex; flex-direction: column; }
            .sidebar { flex: 1; border-left: 1px solid #eee; padding-left: 15px; }
            h2, h3 { color: #333; margin-top: 0; }
            #form-box { display: flex; gap: 10px; margin-bottom: 15px; }
            input[type="text"] { flex: 1; padding: 10px; border: 1px solid #ccc; border-radius: 4px; font-size: 14px; }
            button { background: #007bff; color: white; border: none; padding: 10px 15px; border-radius: 4px; cursor: pointer; font-size: 14px; }
            button:hover { background: #0056b3; }
            #messages { list-style-type: none; padding: 0; height: 350px; overflow-y: auto; border: 1px solid #eee; border-radius: 4px; padding: 10px; background: #fafafa; margin-bottom: 10px; }
            #messages li { padding: 8px 10px; margin-bottom: 8px; border-radius: 4px; background: #e9ecef; word-break: break-all; display: flex; justify-content: space-between; align-items: flex-start; }
            .system-msg { color: #6c757d; font-style: italic; background: #f8f9fa !important; justify-content: center !important; text-align: center; }
            #typing-indicator { height: 20px; font-size: 13px; color: #666; font-style: italic; margin-bottom: 10px; }
            #online-list { list-style-type: none; padding: 0; font-size: 14px; color: #333; }
            #online-list li { margin-bottom: 5px; display: flex; align-items: center; gap: 5px; }
            .dot { height: 8px; width: 8px; background-color: #28a745; border-radius: 50%; display: inline-block; }
            .chat-input-area { display: flex; gap: 10px; align-items: center; }
            .media-preview { max-width: 200px; max-height: 150px; border-radius: 4px; display: block; margin-top: 5px; }
            .file-label { background: #6c757d; color: white; padding: 10px 12px; border-radius: 4px; cursor: pointer; font-size: 14px; display: inline-block; }
            .file-label:hover { background: #5a6268; }
            input[type="file"] { display: none; }
            .delete-btn { background: #dc3545; color: white; border: none; padding: 3px 8px; border-radius: 4px; cursor: pointer; font-size: 12px; margin-left: 10px; }
            .delete-btn:hover { background: #c82333; }
        </style>
    </head>
    <body>
        <div class="chat-container">
            <div class="main-chat">
                <h2>💬 Чат</h2>
                <div id="form-box">
                    <input type="text" id="usernameInput" placeholder="Ваше имя..." autocomplete="off" />
                    <button onclick="connectChat()">Войти</button>
                </div>
                
                <div id="chat-box" style="display: none;">
                    <ul id="messages"></ul>
                    <div id="typing-indicator"></div>
                    
                    <form id="chatForm" action="" onsubmit="sendMessage(event)">
                        <div class="chat-input-area">
                            <input type="text" id="messageText" autocomplete="off" placeholder="Введите сообщение..." oninput="notifyTyping()" />
                            
                            <label class="file-label" title="Прикрепить фото или видео">
                                📎 <input type="file" id="mediaFile" accept="image/*,video/*" onchange="sendFile(event)" />
                            </label>
                            
                            <button type="submit">Отправить</button>
                        </div>
                    </form>
                </div>
            </div>

            <div class="sidebar" id="sidebar-box" style="display: none;">
                <h3>🟢 Онлайн (<span id="online-count">0</span>)</h3>
                <ul id="online-list"></ul>
            </div>
        </div>

        <script>
            let ws = null;
            let username = "";

            function connectChat() {
                const nameInput = document.getElementById("usernameInput").value.trim();
                if (!nameInput) {
                    alert("Пожалуйста, введите имя!");
                    return;
                }
                username = nameInput;
                
                const protocol = window.location.protocol === "https:" ? "wss://" : "ws://";
                const wsUrl = protocol + window.location.host + "/ws/" + encodeURIComponent(username);
                
                ws = new WebSocket(wsUrl);

                ws.onmessage = function(event) {
                    const data = JSON.parse(event.data);
                    const messages = document.getElementById('messages');

                    if (data.type === "history") {
                        messages.innerHTML = "";
                        data.messages.forEach(msg => renderMessage(msg, messages));
                        messages.scrollTop = messages.scrollHeight;
                    }
                    else if (["message", "system", "media"].includes(data.type)) {
                        renderMessage(data, messages);
                        messages.scrollTop = messages.scrollHeight;
                    } 
                    else if (data.type === "delete") {
                        const el = document.getElementById(`msg-${data.id}`);
                        if (el) el.remove();
                    }
                    else if (data.type === "online_list") {
                        const list = document.getElementById('online-list');
                        list.innerHTML = "";
                        document.getElementById('online-count').textContent = data.users.length;
                        data.users.forEach(user => {
                            const li = document.createElement('li');
                            li.innerHTML = `<span class="dot"></span> ${user}`;
                            list.appendChild(li);
                        });
                    }
                    else if (data.type === "typing") {
                        if (data.sender !== username) {
                            const indicator = document.getElementById('typing-indicator');
                            indicator.textContent = `✍️ ${data.sender} печатает сообщение...`;
                            
                            clearTimeout(window.typingTimer);
                            window.typingTimer = setTimeout(() => {
                                indicator.textContent = "";
                            }, 1500);
                        }
                    }
                };

                document.getElementById("form-box").style.display = "none";
                document.getElementById("chat-box").style.display = "block";
                document.getElementById("sidebar-box").style.display = "block";
            }

            function renderMessage(msg, container) {
                const li = document.createElement('li');
                if (msg.id !== undefined) {
                    li.id = `msg-${msg.id}`;
                }

                const contentDiv = document.createElement('div');

                if (msg.type === "system") {
                    li.className = "system-msg";
                    contentDiv.textContent = msg.text;
                } else if (msg.type === "message") {
                    contentDiv.textContent = `${msg.sender}: ${msg.text}`;
                } else if (msg.type === "media") {
                    if (msg.mediaType.startsWith("image/")) {
                        contentDiv.innerHTML = `${msg.sender}:<br><img src="${msg.content}" class="media-preview"/>`;
                    } else if (msg.mediaType.startsWith("video/")) {
                        contentDiv.innerHTML = `${msg.sender}:<br><video src="${msg.content}" class="media-preview" controls></video>`;
                    }
                }

                li.appendChild(contentDiv);

                // Кнопка удаления отображается только если вошедший пользователь — Shuxrat (регистр не важен)
                if (username.toLowerCase() === "shuxrat" && msg.type !== "system" && msg.id !== undefined) {
                    const deleteBtn = document.createElement('button');
                    deleteBtn.className = "delete-btn";
                    deleteBtn.textContent = "Удалить";
                    deleteBtn.onclick = function() {
                        ws.send(JSON.stringify({ action: "delete", id: msg.id }));
                    };
                    li.appendChild(deleteBtn);
                }

                container.appendChild(li);
            }

            function sendMessage(event) {
                event.preventDefault();
                const input = document.getElementById("messageText");
                if (input.value.trim() && ws) {
                    ws.send(JSON.stringify({ action: "message", text: input.value }));
                    input.value = '';
                }
            }

            function sendFile(event) {
                const file = event.target.files[0];
                if (!file || !ws) return;

                const reader = new FileReader();
                reader.onload = function(e) {
                    ws.send(JSON.stringify({
                        action: "media",
                        content: e.target.result,
                        mediaType: file.type
                    }));
                };
                reader.readAsDataURL(file);
                event.target.value = '';
            }

            function notifyTyping() {
                if (ws && ws.readyState === WebSocket.OPEN) {
                    if (!window.isTypingSent) {
                        ws.send(JSON.stringify({ action: "typing" }));
                        window.isTypingSent = true;
                        setTimeout(() => { window.isTypingSent = false; }, 1000);
                    }
                }
            }
        </script>
    </body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def get():
    return HTMLResponse(html)

@app.websocket("/ws/{client_name}")
async def websocket_endpoint(websocket: WebSocket, client_name: str):
    await manager.connect(websocket, client_name)
    await manager.broadcast({
        "type": "system", 
        "text": f"🔔 {client_name} присоединился к чату"
    })
    
    try:
        while True:
            raw_data = await websocket.receive_text()
            data = json.loads(raw_data)
            
            if data["action"] == "message":
                text = data.get("text", "").strip()
                if text:
                    await manager.broadcast({
                        "type": "message",
                        "sender": client_name,
                        "text": text
                    })
            elif data["action"] == "media":
                content = data.get("content")
                media_type = data.get("mediaType")
                if content and media_type:
                    await manager.broadcast({
                        "type": "media",
                        "sender": client_name,
                        "content": content,
                        "mediaType": media_type
                    })
            elif data["action"] == "delete":
                # Серверная проверка безопасности: удалить может только Shuxrat
                if client_name.lower() == "shuxrat":
                    msg_id = data.get("id")
                    if msg_id is not None:
                        await manager.delete_message(msg_id)
            elif data["action"] == "typing":
                await manager.broadcast({
                    "type": "typing",
                    "sender": client_name
                })
                
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        await manager.broadcast_online_users()
        await manager.broadcast({
            "type": "system",
            "text": f"❌ {client_name} покинул чат"
        })
