import time
import requests
from .config import (
    LISTENBRAINZ_TOKEN, LISTENBRAINZ_API_URL, USER_AGENT,
    WEEKLY_JAMS_MBID, DEFAULT_USERNAME, check_internet,
)
from .cache import load_cache, save_cache

# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #
def _api_get(url, headers=None, params=None):
    """GET request with connectivity check and error reporting."""
    if not check_internet():
        raise ConnectionError("No internet connection")
    resp = requests.get(url, headers=headers, params=params)
    if resp.status_code != 200:
        raise ConnectionError(f"API error {resp.status_code}: {resp.text}")
    return resp.json()

def _api_post(url, json=None, headers=None):
    """POST request with connectivity check and error reporting."""
    if not check_internet():
        raise ConnectionError("No internet connection")
    resp = requests.post(url, json=json, headers=headers)
    if resp.status_code != 200:
        raise ConnectionError(f"API error {resp.status_code}: {resp.text}")
    return resp.json()

# --------------------------------------------------------------------------- #
#  Public API
# --------------------------------------------------------------------------- #
def submit_listen(artist_name, track_name, listened_at=None):
    """Submit a single listen to ListenBrainz."""
    if not LISTENBRAINZ_TOKEN:
        print("❌ LISTENBRAINZ_TOKEN not set. Cannot scrobble.")
        return
    if listened_at is None:
        listened_at = int(time.time())
    payload = {
        "listen_type": "single",
        "payload": [{
            "listened_at": listened_at,
            "track_metadata": {
                "artist_name": artist_name,
                "track_name": track_name,
            }
        }]
    }
    headers = {"Authorization": f"Token {LISTENBRAINZ_TOKEN}", "User-Agent": USER_AGENT}
    try:
        _api_post(f"{LISTENBRAINZ_API_URL}/submit-listens", json=payload, headers=headers)
        print(f"✅ Scrobbled: {artist_name} - {track_name}")
    except ConnectionError as e:
        print(f"❌ Scrobble failed: {e}")

def submit_now_playing(artist_name, track_name):
    """Submit a 'now playing' notification."""
    if not LISTENBRAINZ_TOKEN:
        return
    payload = {
        "listen_type": "playing_now",
        "payload": [{
            "track_metadata": {
                "artist_name": artist_name,
                "track_name": track_name,
            }
        }]
    }
    headers = {"Authorization": f"Token {LISTENBRAINZ_TOKEN}", "User-Agent": USER_AGENT}
    try:
        _api_post(f"{LISTENBRAINZ_API_URL}/submit-listens", json=payload, headers=headers)
    except ConnectionError as e:
        print(f"❌ Now playing update failed: {e}")

def clear_now_playing():
    """Remove the now‑playing status from ListenBrainz."""
    if not LISTENBRAINZ_TOKEN:
        return
    payload = {"listen_type": "playing_now", "payload": [{}]}
    headers = {"Authorization": f"Token {LISTENBRAINZ_TOKEN}", "User-Agent": USER_AGENT}
    try:
        _api_post(f"{LISTENBRAINZ_API_URL}/submit-listens", json=payload, headers=headers)
    except ConnectionError as e:
        print(f"❌ Clear now playing failed: {e}")

def get_playlist_tracks(playlist_mbid):
    """Fetch tracks from a ListenBrainz playlist by its MBID (UUID) or full URL."""
    if playlist_mbid.startswith("http"):
        playlist_mbid = playlist_mbid.split("/")[-1]
    url = f"{LISTENBRAINZ_API_URL}/playlist/{playlist_mbid}"
    headers = {"Authorization": f"Token {LISTENBRAINZ_TOKEN}"} if LISTENBRAINZ_TOKEN else {}
    try:
        data = _api_get(url, headers=headers)
    except ConnectionError as e:
        print(f"❌ Failed to fetch playlist: {e}")
        return []
    tracks = []
    for item in data.get('playlist', {}).get('track', []):
        title = item.get('title', 'Unknown Title')
        artist = item.get('creator', 'Unknown Artist')
        tracks.append(f"{artist} - {title}")
    return tracks

def get_liked_tracks():
    """Fetch liked tracks for the default user."""
    if not DEFAULT_USERNAME:
        raise ValueError("LB_USERNAME not set")
    url = f"{LISTENBRAINZ_API_URL}/feedback/user/{DEFAULT_USERNAME}/get-feedback"
    headers = {"Authorization": f"Token {LISTENBRAINZ_TOKEN}"} if LISTENBRAINZ_TOKEN else {}
    params = {"score": 1, "count": 500}
    try:
        data = _api_get(url, headers=headers, params=params)
    except ConnectionError as e:
        raise ConnectionError(f"Failed to fetch liked tracks: {e}")
    feedback_items = data.get('feedback', [])
    cache = load_cache()
    tracks = []
    uncached = []
    for item in feedback_items:
        mbid = item.get('recording_mbid')
        if not mbid:
            continue
        if mbid in cache:
            tracks.append(cache[mbid])
        else:
            uncached.append(mbid)
    if uncached:
        print(f"🔄 Resolving {len(uncached)} new MBIDs (one-time delay)...")
        for mbid in uncached:
            mb_url = f"https://musicbrainz.org/ws/2/recording/{mbid}"
            mb_headers = {"User-Agent": USER_AGENT}
            mb_params = {"fmt": "json", "inc": "artist-credits"}
            try:
                mb_resp = requests.get(mb_url, headers=mb_headers, params=mb_params)
                if mb_resp.status_code == 200:
                    mb_data = mb_resp.json()
                    title = mb_data.get('title')
                    artist_credit = mb_data.get('artist-credit', [])
                    artist = artist_credit[0].get('name') if artist_credit else None
                    if artist and title:
                        track_str = f"{artist} - {title}"
                        tracks.append(track_str)
                        cache[mbid] = track_str
                time.sleep(1.1)
            except Exception:
                continue
        save_cache(cache)
    seen = set()
    ordered = []
    for item in feedback_items:
        mbid = item.get('recording_mbid')
        if mbid and mbid in cache:
            track = cache[mbid]
            if track not in seen:
                seen.add(track)
                ordered.append(track)
    return ordered

def get_weekly_tracks():
    """Return tracks for the user's Weekly Jams playlist (auto‑generated)."""
    if not DEFAULT_USERNAME:
        raise ValueError("LB_USERNAME not set")
    url = f"{LISTENBRAINZ_API_URL}/user/{DEFAULT_USERNAME}/playlists/createdfor"
    headers = {"Authorization": f"Token {LISTENBRAINZ_TOKEN}"} if LISTENBRAINZ_TOKEN else {}
    try:
        data = _api_get(url, headers=headers)
    except ConnectionError as e:
        raise ConnectionError(f"Failed to fetch weekly jams: {e}")
    playlists = data.get("playlists", [])
    for item in playlists:
        p = item.get("playlist", {})
        title = p.get("title", "")
        if title.startswith("Weekly Jams for "):
            identifier = p.get("identifier", "")
            if identifier.startswith("http"):
                identifier = identifier.split("/")[-1]
            return get_playlist_tracks(identifier)
    # Fallback: hardcoded MBID
    return get_playlist_tracks(WEEKLY_JAMS_MBID)

def get_weekly_exploration_tracks():
    """Return tracks for the user's Weekly Exploration playlist (auto‑generated)."""
    if not DEFAULT_USERNAME:
        raise ValueError("LB_USERNAME not set")
    url = f"{LISTENBRAINZ_API_URL}/user/{DEFAULT_USERNAME}/playlists/createdfor"
    headers = {"Authorization": f"Token {LISTENBRAINZ_TOKEN}"} if LISTENBRAINZ_TOKEN else {}
    try:
        data = _api_get(url, headers=headers)
    except ConnectionError as e:
        raise ConnectionError(f"Failed to fetch weekly exploration: {e}")
    playlists = data.get("playlists", [])
    for item in playlists:
        p = item.get("playlist", {})
        title = p.get("title", "")
        if title.startswith("Weekly Exploration for "):
            identifier = p.get("identifier", "")
            if identifier.startswith("http"):
                identifier = identifier.split("/")[-1]
            return get_playlist_tracks(identifier)
    return []

def get_user_playlists():
    """Return list of (title, identifier) for the user's playlists."""
    if not DEFAULT_USERNAME:
        raise ValueError("LB_USERNAME not set")
    url = f"{LISTENBRAINZ_API_URL}/user/{DEFAULT_USERNAME}/playlists"
    headers = {"Authorization": f"Token {LISTENBRAINZ_TOKEN}"} if LISTENBRAINZ_TOKEN else {}
    params = {"count": 100}
    try:
        data = _api_get(url, headers=headers, params=params)
    except ConnectionError as e:
        raise ConnectionError(f"Failed to fetch playlists: {e}")
    playlists = []
    for item in data.get('playlists', []):
        p = item.get('playlist', {})
        title = p.get('title', 'Untitled')
        mbid = p.get('identifier', '')
        if not mbid:
            continue
        if mbid.startswith("http"):
            mbid = mbid.split("/")[-1]
        playlists.append((title, mbid))
    return playlists
