"""What is playing on the PC and how to control it — shared by the phone server
(modules/local_api.py) and the web panel (pulse_pc/services/web_panel).

The built-in PulseDeck player and media sessions of other apps (Spotify, browsers …)
look the same to callers.
"""
import asyncio

from modules import now_playing, player_bridge


def own_player():
    """State of the built-in player in the same shape as a media session."""
    own = player_bridge.snapshot()
    return {"id": "pulse", "source": "PulseDeck", "kind": "own", "title": own["title"], "artist": own["artist"],
            "album": own["album"], "status": own["status"], "position": own["position"],
            "duration": own["duration"], "can_prev": True, "can_next": True,
            "cover": own["cover_key"] if own["cover"] else "", "volume": own["volume"]}


async def external_player(source=None):
    return await now_playing.state(source) if now_playing.AVAILABLE else None


async def current_player(source=""):
    """source: '' = automatic, 'pulse' = built-in player, anything else = app id of a media session."""
    own = player_bridge.snapshot()
    if source == "pulse":
        return own_player() if own["active"] else None
    if source:
        return await external_player(source)
    external = await external_player()
    # The built-in player wins unless it is paused while another app is playing.
    if own["active"] and (own["status"] == "playing" or not external or external["status"] != "playing"):
        return own_player()
    return external


async def control_player(cmd, value=None, source=""):
    if cmd not in ("toggle", "play", "pause", "next", "prev", "seek", "volume"):
        raise ValueError("Неизвестная команда плеера.")
    own = player_bridge.snapshot()
    if source == "pulse" or (not source and own["active"]):
        player_bridge.send(cmd, value)
        return
    if cmd == "volume":
        raise ValueError("Громкость плеера доступна только во встроенном плеере PulseDeck.")
    handled = now_playing.AVAILABLE and await now_playing.command(cmd, value, source or None)
    if not handled and source:
        raise ValueError("Этот источник больше не играет.")
    if not handled:
        keys = {"toggle": "playpause", "play": "playpause", "pause": "playpause", "next": "nexttrack", "prev": "prevtrack"}
        if cmd not in keys:
            raise ValueError("Сейчас ничего не играет.")
        from modules import keys as media_keys
        await asyncio.to_thread(media_keys.press, keys[cmd])


async def sessions():
    """Everything that can be controlled: the built-in player and media sessions of other apps."""
    items = await now_playing.sessions() if now_playing.AVAILABLE else []
    own = player_bridge.snapshot()
    if own["active"]:
        items.insert(0, {"id": "pulse", "source": "PulseDeck", "kind": "own", "title": own["title"],
                         "artist": own["artist"], "status": own["status"], "current": False})
    return items


def cover(key):
    """(bytes, content type) of the cover with this key, or None."""
    own = player_bridge.snapshot()
    data = own["cover"] if own["cover"] and own["cover_key"] == key else now_playing.cover_bytes(key)
    if not data:
        return None
    return data, "image/png" if data[1:4] == b"PNG" else "image/jpeg"
