"""
ws.py — Real-time chat over WebSockets.

Clients connect to:   ws://<host>/ws/chats/{chat_id}?token=<access_token>

The token is the same JWT access token used for the REST API. It's passed as a
query parameter because browsers can't set an Authorization header on a
WebSocket handshake. Messages a client sends are persisted and broadcast to
every participant currently connected to that chat.

NOTE: connections are tracked in memory, so this works with a single uvicorn
worker (fine for development). For multiple workers, back the manager with a
shared pub/sub (e.g. Redis).
"""
import json
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from db.database import SessionLocal
from db.models import Chat, Message, User
from server.security import decode_access_token

router = APIRouter()


class ConnectionManager:
    """Tracks the set of live sockets in each chat room."""

    def __init__(self) -> None:
        self._rooms: dict[str, set[WebSocket]] = {}

    async def connect(self, chat_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._rooms.setdefault(chat_id, set()).add(ws)

    def disconnect(self, chat_id: str, ws: WebSocket) -> None:
        room = self._rooms.get(chat_id)
        if not room:
            return
        room.discard(ws)
        if not room:
            self._rooms.pop(chat_id, None)

    async def broadcast(self, chat_id: str, payload: dict) -> None:
        for ws in list(self._rooms.get(chat_id, ())):
            try:
                await ws.send_json(payload)
            except Exception:
                self.disconnect(chat_id, ws)


manager = ConnectionManager()


def _participants(chat: Chat) -> set[str]:
    return {str(chat.participant_1), str(chat.participant_2)}


@router.websocket("/ws/chats/{chat_id}")
async def chat_socket(websocket: WebSocket, chat_id: str):
    token = websocket.query_params.get("token")
    user_id = decode_access_token(token) if token else None
    if not user_id:
        await websocket.close(code=1008)          # 1008 = policy violation
        return

    # Authorize: the user must be a participant in this chat.
    with SessionLocal() as db:
        user = db.query(User).filter(User.user_id == user_id).first()
        chat = db.query(Chat).filter(Chat.chat_id == chat_id).first()
        if not user or not user.email_verified or not chat or user_id not in _participants(chat):
            await websocket.close(code=1008)
            return

    await manager.connect(chat_id, websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except Exception:
                continue
            content = data.get("content", "") if isinstance(data, dict) else ""
            if not isinstance(content, str) or not content.strip():
                continue

            with SessionLocal() as db:
                msg = Message(
                    chat_id=uuid.UUID(chat_id),
                    sender_id=uuid.UUID(user_id),
                    content=content.strip(),
                )
                db.add(msg)
                db.commit()
                db.refresh(msg)
                payload = {
                    "message_id": str(msg.message_id),
                    "chat_id":    str(msg.chat_id),
                    "sender_id":  str(msg.sender_id),
                    "content":    msg.content,
                    "is_read":    msg.is_read,
                    "sent_at":    msg.sent_at.isoformat(),
                }
            await manager.broadcast(chat_id, payload)
    except WebSocketDisconnect:
        manager.disconnect(chat_id, websocket)
    except Exception:
        manager.disconnect(chat_id, websocket)
        try:
            await websocket.close()
        except Exception:
            pass
