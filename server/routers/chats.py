from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db.models import Chat, Message, User
from server.dependencies import get_blocked_user_ids, get_verified_user, get_db
from server.schemas import ChatResponse, MessageResponse, SendMessageRequest

router = APIRouter(prefix="/chats", tags=["chats"])


@router.get("", response_model=List[ChatResponse])
def list_chats(
    current_user: User    = Depends(get_verified_user),
    db:           Session = Depends(get_db),
):
    return (
        db.query(Chat)
        .filter(
            (Chat.participant_1 == current_user.user_id)
            | (Chat.participant_2 == current_user.user_id)
        )
        .order_by(Chat.created_at.desc())
        .all()
    )


@router.get("/{chat_id}/messages", response_model=List[MessageResponse])
def get_messages(
    chat_id:      str,
    current_user: User    = Depends(get_verified_user),
    db:           Session = Depends(get_db),
):
    chat = _get_or_403(chat_id, current_user, db)

    # Mark incoming unread messages as read
    db.query(Message).filter(
        Message.chat_id   == chat.chat_id,
        Message.sender_id != current_user.user_id,
        Message.is_read   == False,  # noqa: E712
    ).update({"is_read": True})
    db.commit()

    return (
        db.query(Message)
        .filter(Message.chat_id == chat.chat_id)
        .order_by(Message.sent_at)
        .all()
    )


@router.post("/{chat_id}/messages", response_model=MessageResponse, status_code=201)
def send_message(
    chat_id:      str,
    body:         SendMessageRequest,
    current_user: User    = Depends(get_verified_user),
    db:           Session = Depends(get_db),
):
    chat = _get_or_403(chat_id, current_user, db)

    other_id = chat.participant_2 if chat.participant_1 == current_user.user_id else chat.participant_1
    blocked_ids = get_blocked_user_ids(current_user.user_id, db)
    if other_id in blocked_ids:
        raise HTTPException(status_code=403, detail="You can't message a blocked user")

    msg = Message(
        chat_id=chat.chat_id,
        sender_id=current_user.user_id,
        content=body.content,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


# ── helper ────────────────────────────────────────────────────────────────────

def _get_or_403(chat_id: str, user: User, db: Session) -> Chat:
    chat = db.query(Chat).filter(Chat.chat_id == chat_id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    if user.user_id not in (chat.participant_1, chat.participant_2):
        raise HTTPException(status_code=403, detail="Not your chat")
    return chat
