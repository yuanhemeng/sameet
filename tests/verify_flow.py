"""Run against a local Sameet server to verify the complete two-player flow."""

from __future__ import annotations

import asyncio
import json
import urllib.request

import websockets


BASE_URL = "http://127.0.0.1:8000"
WS_URL = "ws://127.0.0.1:8000"


def post(path: str, payload: dict) -> dict:
    request = urllib.request.Request(
        BASE_URL + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        return json.load(response)


async def next_state(socket, status: str, round_number: int | None = None) -> dict:
    while True:
        message = json.loads(await asyncio.wait_for(socket.recv(), timeout=6))
        if message.get("type") != "state":
            continue
        room = message["room"]
        if room["status"] == status and (round_number is None or room["round"] == round_number):
            return message


async def main() -> None:
    owner = post("/api/rooms", {"name": "小林", "round_seconds": 30})
    guest = post(f"/api/rooms/{owner['code']}/join", {"name": "阿青"})
    owner_uri = f"{WS_URL}/ws/{owner['code']}?player_id={owner['playerId']}&token={owner['token']}"
    guest_uri = f"{WS_URL}/ws/{guest['code']}?player_id={guest['playerId']}&token={guest['token']}"

    async with websockets.connect(owner_uri) as first, websockets.connect(guest_uri) as second:
        await first.send(json.dumps({"action": "start"}))
        await asyncio.gather(next_state(first, "playing", 1), next_state(second, "playing", 1))

        await first.send(json.dumps({"action": "submit", "word": "苹果"}))
        await second.send(json.dumps({"action": "submit", "word": "香蕉"}))
        revealed, _ = await asyncio.gather(next_state(first, "reveal", 1), next_state(second, "reveal", 1))
        assert revealed["room"]["history"][0]["matched"] is False

        await asyncio.gather(next_state(first, "playing", 2), next_state(second, "playing", 2))
        await first.send(json.dumps({"action": "submit", "word": " 水果 "}))
        await second.send(json.dumps({"action": "submit", "word": "水果"}))
        finished, _ = await asyncio.gather(next_state(first, "finished", 2), next_state(second, "finished", 2))
        assert finished["room"]["history"][-1]["matched"] is True
        assert len(finished["room"]["history"]) == 2
        print(f"PASS: room {owner['code']} finished in 2 rounds")


if __name__ == "__main__":
    asyncio.run(main())
