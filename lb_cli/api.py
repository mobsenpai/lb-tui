import time
import requests
from .config import LISTENBRAINZ_TOKEN, LISTENBRAINZ_API_URL, USER_AGENT, WEEKLY_JAMS_MBID, DEFAULT_USERNAME
from .cache import load_cache, save_cache

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
    resp = requests.post(f"{LISTENBRAINZ_API_URL}/submit-listens", json=payload, headers=headers)
    if resp.status_code == 200:
        print(f"✅ Scrobbled: {artist_name} - {track_name}")
    else:
        print(f"❌ Scrobble failed: {resp.text}")

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
    resp = requests.post(f"{LISTENBRAINZ_API_URL}/submit-listens", json=payload, headers=headers)
    if resp.status_code == 200:
        print(f"🎵 Now playing: {artist_name} - {track_name}")
    else:
        print(f"❌ Now playing update failed: {resp.text}")

def get_playlist_tracks(playlist_mbid):
    """Fetch tracks from a ListenBrainz playlist by its MBID (UUID) or full URL."""
    if playlist_mbid.startswith("http"):
        playlist_mbid = playlist_mbid.split("/")[-1]
    url = f"{LISTENBRAINZ_API_URL}/playlist/{playlist_mbid}"
    headers = {"Authorization": f"Token {LISTENBRAINZ_TOKEN}"} if LISTENBRAINZ_TOKEN else {}
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        return []
    data = resp.json()
    tracks = []
    for item in data.get('playlist', {}).get('track', []):
        title = item.get('title', 'Unknown Title')
        artist = item.get('creator', 'Unknown Artist')
        tracks.append(f"{artist} - {title}")
    return tracks

def get_liked_tracks():
    """Fetch liked tracks for the default user."""
    if not DEFAULT_USERNAME:
        print("❌ LB_USERNAME not set.")
        return []
    username = DEFAULT_USERNAME
    url = f"{LISTENBRAINZ_API_URL}/feedback/user/{username}/get-feedback"
    headers = {"Authorization": f"Token {LISTENBRAINZ_TOKEN}"} if LISTENBRAINZ_TOKEN else {}
    params = {"score": 1, "count": 500}
    resp = requests.get(url, headers=headers, params=params)
    if resp.status_code != 200:
        return []
    data = resp.json()
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
            except:
                continue
        save_cache(cache)

    # Deduplicate and maintain order
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
    """Return tracks for the default user's weekly jams playlist."""
    if not DEFAULT_USERNAME:
        print("❌ LB_USERNAME not set.")
        return []
    username = DEFAULT_USERNAME
    # Use hardcoded MBID for mobsenpai; fallback to searching user playlists
    if username == "mobsenpai":
        return get_playlist_tracks(WEEKLY_JAMS_MBID)
    # Fallback: search for "Weekly Jams" in user's playlists
    url = f"{LISTENBRAINZ_API_URL}/user/{username}/playlists"
    headers = {"Authorization": f"Token {LISTENBRAINZ_TOKEN}"} if LISTENBRAINZ_TOKEN else {}
    params = {"count": 100}
    resp = requests.get(url, headers=headers, params=params)
    if resp.status_code == 200:
        data = resp.json()
        for item in data.get('playlists', []):
            p = item.get('playlist', {})
            if 'Weekly Jams' in p.get('title', ''):
                identifier = p.get('identifier', '')
                if identifier.startswith("http"):
                    return get_playlist_tracks(identifier.split("/")[-1])
                return get_playlist_tracks(identifier)
    return []
