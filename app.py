from __future__ import annotations

import asyncio
import re
import secrets
import string
import time
import unicodedata
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator


BASE_DIR = Path(__file__).resolve().parent
ROOM_TTL_SECONDS = 30 * 60
REVEAL_SECONDS = 3
ROOM_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def normalize_word(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).strip().split()).casefold()


class CreateRoomRequest(BaseModel):
    name: str = Field(min_length=1, max_length=16)
    round_seconds: int = Field(ge=10, le=300)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        cleaned = " ".join(value.strip().split())
        if not cleaned:
            raise ValueError("请输入昵称")
        return cleaned


class JoinRoomRequest(BaseModel):
    name: str = Field(min_length=1, max_length=16)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        cleaned = " ".join(value.strip().split())
        if not cleaned:
            raise ValueError("请输入昵称")
        return cleaned


@dataclass
class Player:
    id: str
    token: str
    name: str
    connected: bool = False
    submitted_word: str | None = None
    sockets: set[WebSocket] = field(default_factory=set)


@dataclass
class Room:
    code: str
    owner_id: str
    round_seconds: int
    players: dict[str, Player] = field(default_factory=dict)
    status: str = "waiting"
    round_number: int = 0
    deadline: float | None = None
    history: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    timer_task: asyncio.Task[None] | None = None
    transition_id: int = 0

    def public_state(self, viewer_id: str) -> dict[str, Any]:
        viewer = self.players.get(viewer_id)
        return {
            "type": "state",
            "room": {
                "code": self.code,
                "ownerId": self.owner_id,
                "roundSeconds": self.round_seconds,
                "status": self.status,
                "round": self.round_number,
                "deadline": self.deadline,
                "serverTime": time.time(),
                "history": self.history,
                "players": [
                    {
                        "id": player.id,
                        "name": player.name,
                        "connected": player.connected,
                        "submitted": player.submitted_word is not None,
                    }
                    for player in self.players.values()
                ],
            },
            "you": {
                "id": viewer_id,
                "submitted": bool(viewer and viewer.submitted_word is not None),
                "isOwner": viewer_id == self.owner_id,
            },
        }


class RoomManager:
    def __init__(self) -> None:
        self.rooms: dict[str, Room] = {}
        self.lock = asyncio.Lock()

    @staticmethod
    def new_player(name: str) -> Player:
        return Player(
            id=secrets.token_urlsafe(9),
            token=secrets.token_urlsafe(24),
            name=name,
        )

    def new_code(self) -> str:
        for _ in range(100):
            code = "".join(secrets.choice(ROOM_ALPHABET) for _ in range(6))
            if code not in self.rooms:
                return code
        raise RuntimeError("无法生成房间码")

    async def create(self, name: str, round_seconds: int) -> tuple[Room, Player]:
        async with self.lock:
            player = self.new_player(name)
            room = Room(
                code=self.new_code(),
                owner_id=player.id,
                round_seconds=round_seconds,
            )
            room.players[player.id] = player
            self.rooms[room.code] = room
            return room, player

    async def join(self, code: str, name: str) -> tuple[Room, Player]:
        async with self.lock:
            room = self.rooms.get(code)
            if not room:
                raise HTTPException(404, "房间不存在或已过期")
            if room.status != "waiting":
                raise HTTPException(409, "游戏已经开始")
            if len(room.players) >= 2:
                raise HTTPException(409, "房间已满")
            if any(normalize_word(p.name) == normalize_word(name) for p in room.players.values()):
                raise HTTPException(409, "请使用不同的昵称")
            player = self.new_player(name)
            room.players[player.id] = player
            room.last_active = time.time()
            return room, player

    async def broadcast(self, room: Room) -> None:
        stale: list[tuple[Player, WebSocket]] = []
        for player in list(room.players.values()):
            payload = room.public_state(player.id)
            for socket in list(player.sockets):
                try:
                    await socket.send_json(payload)
                except Exception:
                    stale.append((player, socket))
        for player, socket in stale:
            player.sockets.discard(socket)
            player.connected = bool(player.sockets)

    async def send_error(self, socket: WebSocket, message: str) -> None:
        await socket.send_json({"type": "error", "message": message})

    async def start(self, room: Room, player_id: str) -> None:
        async with self.lock:
            if player_id != room.owner_id:
                raise ValueError("只有房主可以开始游戏")
            if room.status != "waiting":
                raise ValueError("游戏已经开始")
            if len(room.players) != 2:
                raise ValueError("需要两名玩家才能开始")
            if not all(player.connected for player in room.players.values()):
                raise ValueError("请等待两名玩家都在线")
            self._begin_round(room, 1)
        await self.broadcast(room)

    def _begin_round(self, room: Room, number: int) -> None:
        room.transition_id += 1
        room.status = "playing"
        room.round_number = number
        room.deadline = time.time() + room.round_seconds
        for player in room.players.values():
            player.submitted_word = None
        if room.timer_task:
            room.timer_task.cancel()
        transition_id = room.transition_id
        room.timer_task = asyncio.create_task(self._expire_round(room, transition_id))

    async def _expire_round(self, room: Room, transition_id: int) -> None:
        try:
            await asyncio.sleep(room.round_seconds)
            async with self.lock:
                if room.transition_id != transition_id or room.status != "playing":
                    return
                if all(player.submitted_word is not None for player in room.players.values()):
                    return
                room.status = "timed_out"
                room.deadline = None
                room.last_active = time.time()
            await self.broadcast(room)
        except asyncio.CancelledError:
            return

    async def submit(self, room: Room, player_id: str, word: str) -> None:
        cleaned = " ".join(word.strip().split())
        if not cleaned:
            raise ValueError("请输入一个词")
        if len(cleaned) > 20:
            raise ValueError("词语不能超过 20 个字符")

        should_reveal = False
        async with self.lock:
            if room.status not in {"playing", "timed_out"}:
                raise ValueError("当前不能提交")
            player = room.players[player_id]
            if player.submitted_word is not None:
                raise ValueError("本轮已经提交")
            player.submitted_word = cleaned
            room.last_active = time.time()
            should_reveal = all(p.submitted_word is not None for p in room.players.values())
            if should_reveal:
                room.transition_id += 1
                if room.timer_task:
                    room.timer_task.cancel()
                ordered = list(room.players.values())
                words = [p.submitted_word or "" for p in ordered]
                matched = normalize_word(words[0]) == normalize_word(words[1])
                room.history.append(
                    {
                        "round": room.round_number,
                        "answers": [
                            {"playerId": p.id, "name": p.name, "word": p.submitted_word}
                            for p in ordered
                        ],
                        "matched": matched,
                    }
                )
                room.status = "finished" if matched else "reveal"
                room.deadline = None
                transition_id = room.transition_id
        await self.broadcast(room)

        if should_reveal and room.status == "reveal":
            room.timer_task = asyncio.create_task(self._next_round(room, transition_id))

    async def _next_round(self, room: Room, transition_id: int) -> None:
        try:
            await asyncio.sleep(REVEAL_SECONDS)
            async with self.lock:
                if room.transition_id != transition_id or room.status != "reveal":
                    return
                self._begin_round(room, room.round_number + 1)
            await self.broadcast(room)
        except asyncio.CancelledError:
            return

    async def restart(self, room: Room, player_id: str) -> None:
        async with self.lock:
            if player_id != room.owner_id:
                raise ValueError("只有房主可以再开一局")
            if room.status != "finished":
                raise ValueError("当前不能重新开始")
            room.history.clear()
            self._begin_round(room, 1)
        await self.broadcast(room)

    async def cleanup(self) -> None:
        while True:
            await asyncio.sleep(60)
            now = time.time()
            async with self.lock:
                expired = [
                    code
                    for code, room in self.rooms.items()
                    if not any(p.connected for p in room.players.values())
                    and now - room.last_active > ROOM_TTL_SECONDS
                ]
                for code in expired:
                    room = self.rooms.pop(code)
                    if room.timer_task:
                        room.timer_task.cancel()


manager = RoomManager()


@asynccontextmanager
async def lifespan(_: FastAPI):
    cleanup_task = asyncio.create_task(manager.cleanup())
    yield
    cleanup_task.cancel()
    for room in manager.rooms.values():
        if room.timer_task:
            room.timer_task.cancel()


app = FastAPI(title="同词相遇", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/room/{code}", include_in_schema=False)
async def room_page(code: str) -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "room.html")


@app.get("/api/rooms/{code}")
async def room_exists(code: str) -> dict[str, Any]:
    room = manager.rooms.get(code.upper())
    if not room:
        raise HTTPException(404, "房间不存在或已过期")
    return {
        "code": room.code,
        "joinable": room.status == "waiting" and len(room.players) < 2,
        "status": room.status,
    }


@app.post("/api/rooms", status_code=201)
async def create_room(payload: CreateRoomRequest) -> dict[str, str]:
    room, player = await manager.create(payload.name, payload.round_seconds)
    return {"code": room.code, "playerId": player.id, "token": player.token}


@app.post("/api/rooms/{code}/join", status_code=201)
async def join_room(code: str, payload: JoinRoomRequest) -> dict[str, str]:
    room, player = await manager.join(code.upper(), payload.name)
    await manager.broadcast(room)
    return {"code": room.code, "playerId": player.id, "token": player.token}


@app.websocket("/ws/{code}")
async def websocket_endpoint(websocket: WebSocket, code: str) -> None:
    room = manager.rooms.get(code.upper())
    player_id = websocket.query_params.get("player_id", "")
    token = websocket.query_params.get("token", "")
    player = room.players.get(player_id) if room else None
    if not room or not player or not secrets.compare_digest(player.token, token):
        await websocket.close(code=4401, reason="身份无效")
        return

    await websocket.accept()
    player.sockets.add(websocket)
    player.connected = True
    room.last_active = time.time()
    await manager.broadcast(room)
    try:
        while True:
            message = await websocket.receive_json()
            action = message.get("action")
            try:
                if action == "start":
                    await manager.start(room, player.id)
                elif action == "submit":
                    await manager.submit(room, player.id, str(message.get("word", "")))
                elif action == "restart":
                    await manager.restart(room, player.id)
                elif action == "ping":
                    await websocket.send_json({"type": "pong", "serverTime": time.time()})
                else:
                    raise ValueError("未知操作")
            except ValueError as exc:
                await manager.send_error(websocket, str(exc))
    except WebSocketDisconnect:
        pass
    finally:
        player.sockets.discard(websocket)
        player.connected = bool(player.sockets)
        room.last_active = time.time()
        await manager.broadcast(room)

