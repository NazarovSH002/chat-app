from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import json

app = FastAPI()
templates = Jinja2Templates(directory="templates")

class ConnectionManager:
    def __init__(self):
        # Храним активные соединения в виде словаря: {WebSocket: client_name}
        self.active_connections: dict[WebSocket, str] = {}

    async def connect(self, websocket: WebSocket, client_name: str):
        await websocket.accept()
        self.active_connections[websocket] = client_name
        await self.broadcast_online_users()

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            del self.active_connections[websocket]

    async def broadcast(self, data: dict):
        message = json.dumps(data)
        for connection in self.active_connections.keys():
            try:
                await connection.send_text(message)
            except Exception:
                pass

    async def broadcast_online_users(self):
        users = list(self.active_connections.values())
        await self.broadcast({"type": "online_list", "users": users})

manager = ConnectionManager()

@app.get("/", response_class=HTMLResponse)
async def get(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

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
            elif data["action"] == "typing":
                # Пересылаем всем остальным, что этот юзер печатает
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