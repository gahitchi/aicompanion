"""Spotify playback control via spotipy (search + play / pause / now-playing).

Spotify has no app-password path, so it's OAuth like calendar. One-time setup:
create an app at developer.spotify.com, add JADE_SPOTIFY_REDIRECT_URI (default
http://localhost:8888/callback) to its redirect URIs, put the client id/secret
in .env, then run `jade --auth-spotify` once to grant access. The token caches
at ~/.aicompanion/spotify_token.json and auto-refreshes, so the headless service
never needs the browser again.

All three tools are SAFE (playback control, non-destructive) and owner-neutral —
a household member may play music. When Spotify isn't configured they fall back
to the local playerctl/MPRIS media tools so "play"/"pause" still do something.

Note: starting playback by name needs Spotify **Premium** and an active device
(open the app on a phone/desktop once); without one, Spotify reports "no active
device" and we say so plainly. Module named `spotify` — no stdlib clash.
"""
import os
from pathlib import Path

SCOPES = "user-modify-playback-state user-read-playback-state"
_CONFIG_DIR = Path.home() / ".aicompanion"
TOKEN_PATH = _CONFIG_DIR / "spotify_token.json"


def _redirect_uri() -> str:
    return os.environ.get("JADE_SPOTIFY_REDIRECT_URI", "http://localhost:8888/callback")


def _creds():
    """(client_id, client_secret); either is None when unset."""
    return (os.environ.get("JADE_SPOTIFY_CLIENT_ID"),
            os.environ.get("JADE_SPOTIFY_CLIENT_SECRET"))


def _configured() -> bool:
    cid, secret = _creds()
    return bool(cid and secret)


def _setup_hint() -> str:
    return ("Spotify isn't connected. Create an app at developer.spotify.com, add "
            f"{_redirect_uri()} to its redirect URIs, put JADE_SPOTIFY_CLIENT_ID and "
            "JADE_SPOTIFY_CLIENT_SECRET in .env, then run `jade --auth-spotify` once.")


def _oauth(open_browser: bool = False):
    """A SpotifyOAuth bound to the cached token. open_browser stays False for the
    service so it can never block on a prompt; authorize() flips it on."""
    from spotipy.oauth2 import SpotifyOAuth
    cid, secret = _creds()
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return SpotifyOAuth(
        client_id=cid, client_secret=secret, redirect_uri=_redirect_uri(),
        scope=SCOPES, cache_path=str(TOKEN_PATH), open_browser=open_browser,
    )


def _client():
    """Authenticated client, or None if not set up / no cached token (never
    raises, never prompts — only uses an already-cached token, refreshing it)."""
    if not _configured():
        return None
    try:
        import spotipy
        auth = _oauth()
        token = auth.cache_handler.get_cached_token()
        if not token:
            return None
        if auth.is_token_expired(token):
            token = auth.refresh_access_token(token["refresh_token"])
        return spotipy.Spotify(auth=token["access_token"])
    except Exception:
        return None


def authorize() -> str:
    """One-time interactive OAuth flow — called by `jade --auth-spotify`."""
    if not _configured():
        return _setup_hint()
    try:
        _oauth(open_browser=True).get_access_token(as_dict=False)
        return f"Spotify connected — token saved to {TOKEN_PATH}."
    except Exception as e:
        return f"Spotify auth failed: {type(e).__name__}: {e}"


def _active_device(sp):
    """An active device id (preferring one already active), or None."""
    try:
        devices = sp.devices().get("devices", [])
    except Exception:
        return None
    if not devices:
        return None
    for d in devices:
        if d.get("is_active"):
            return d["id"]
    return devices[0]["id"]


def _playback_error(e) -> str:
    low = str(e).lower()
    if "premium" in low:
        return "Spotify playback control needs a Premium account."
    if "no active device" in low or ("device" in low and "not found" in low):
        return ("No active Spotify device. Open Spotify somewhere and start it "
                "playing once so it shows up, then ask again.")
    return f"Spotify error: {type(e).__name__}: {e}"


def _best_match(sp, query: str):
    """First track match → {'uris':[uri]}; else artist/playlist/album →
    {'context_uri':uri}. None if nothing matches. Each carries a spoken label."""
    res = sp.search(q=query, type="track,artist,album,playlist", limit=1)
    tracks = (res.get("tracks") or {}).get("items") or []
    if tracks:
        t = tracks[0]
        artists = ", ".join(a["name"] for a in t.get("artists", []))
        return {"uris": [t["uri"]], "label": f"{t['name']} by {artists}"}
    for key, kind in (("artists", "artist"), ("playlists", "playlist"), ("albums", "album")):
        items = (res.get(key) or {}).get("items") or []
        if items:
            it = items[0]
            return {"context_uri": it["uri"], "label": f"{it['name']} ({kind})"}
    return None


def spotify_play(query: str = "") -> str:
    """Play a track/artist/album/playlist by name on Spotify, or resume current
    playback if no query. Falls back to local playerctl when Spotify isn't set up."""
    sp = _client()
    if sp is None:
        from tools.media import media_play
        local = media_play()
        if query:
            return (f"Spotify isn't connected, so I can't search for '{query}'. "
                    f"Resumed local playback instead. {_setup_hint()}")
        return local
    device = _active_device(sp)
    if device is None:
        return ("Spotify's connected but there's no active device. Open Spotify on "
                "your phone or computer and play something once, then ask again.")
    if not query:
        try:
            sp.start_playback(device_id=device)
            return "Playing."
        except Exception as e:
            return _playback_error(e)
    try:
        match = _best_match(sp, query)
    except Exception as e:
        return f"Spotify search error: {type(e).__name__}: {e}"
    if not match:
        return f"Couldn't find anything on Spotify for '{query}'."
    try:
        if "uris" in match:
            sp.start_playback(device_id=device, uris=match["uris"])
        else:
            sp.start_playback(device_id=device, context_uri=match["context_uri"])
        return f"Playing {match['label']}."
    except Exception as e:
        return _playback_error(e)


def spotify_pause() -> str:
    """Pause Spotify playback (or local playback if Spotify isn't set up)."""
    sp = _client()
    if sp is None:
        from tools.media import media_pause
        return media_pause()
    try:
        sp.pause_playback()
        return "Paused."
    except Exception as e:
        return _playback_error(e)


def spotify_now_playing() -> str:
    """What's currently playing on Spotify (or locally if Spotify isn't set up)."""
    sp = _client()
    if sp is None:
        from tools.media import media_status
        return media_status()
    try:
        cur = sp.current_playback()
    except Exception as e:
        return f"Spotify error: {type(e).__name__}: {e}"
    if not cur or not cur.get("item"):
        return "Nothing's playing on Spotify right now."
    item = cur["item"]
    artists = ", ".join(a["name"] for a in item.get("artists", []))
    state = "Playing" if cur.get("is_playing") else "Paused"
    return f"{state}: {item['name']} by {artists}."
