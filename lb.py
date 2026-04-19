#!/usr/bin/env python3
"""
ListenBrainz CLI Music Player
Commands:
  play <query>              Search YouTube and play the first result
  scrobble <artist> <title>    Submit a listen
  nowplaying <artist> <title>  Set currently playing
  playlist <mbid_or_url>    Play a ListenBrainz playlist by UUID or URL
  weekly-play [username]    Play your latest weekly jams playlist
  liked [username]          Play your loved (liked) tracks
"""

import argparse
import os
import subprocess
import sys
import time
import urllib.parse

import requests
import yt_dlp

# ----------------------------------------------------------------------
# CONFIGURATION
# ----------------------------------------------------------------------
LISTENBRAINZ_TOKEN = "ccf7c17f-8fdd-4190-a502-c929137440cb"
LISTENBRAINZ_API_URL = "https://api.listenbrainz.org/1"
USER_AGENT = "LB-CLI-Player/2.0"

# ----------------------------------------------------------------------
# ListenBrainz API Helpers
# ----------------------------------------------------------------------
def submit_listen(artist_name, track_name, listened_at=None):
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
    headers = {"Authorization": f"Token {LISTENBRAINZ_TOKEN}", "User-Agent": USER_AGENT}
    try:
        resp = requests.get(url, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            playlist_title = data.get('playlist', {}).get('title', 'Untitled')
            tracks = []
            for item in data.get('playlist', {}).get('track', []):
                title = item.get('title', 'Unknown Title')
                artist = item.get('creator', 'Unknown Artist')
                tracks.append(f"{artist} - {title}")
            print(f"📋 Found playlist: {playlist_title} ({len(tracks)} tracks)")
            return tracks
        else:
            print(f"❌ Failed to fetch playlist: {resp.status_code}")
            return None
    except Exception as e:
        print(f"❌ Error fetching playlist: {e}")
        return None

def get_latest_weekly_jams_mbid(username):
    """Find the MBID of the most recent 'Weekly Jams' playlist."""
    if username == "mobsenpai":
        return "2b85e1a1-3f4f-4eb2-8abb-bbae2a01fcf6"

    url = f"{LISTENBRAINZ_API_URL}/user/{username}/playlists"
    headers = {"Authorization": f"Token {LISTENBRAINZ_TOKEN}", "User-Agent": USER_AGENT}
    params = {"count": 100, "offset": 0}
    try:
        resp = requests.get(url, headers=headers, params=params)
        data = resp.json()
        for item in data.get('playlists', []):
            p = item.get('playlist', {})
            if 'Weekly Jams' in p.get('title', ''):
                identifier = p.get('identifier', '')
                if identifier.startswith("http"):
                    return identifier.split("/")[-1]
                return identifier
        return None
    except Exception as e:
        print(f"❌ Error: {e}")
        return None

def get_liked_tracks(username, count=100):
    """Fetch liked tracks using MusicBrainz for reliable artist/title metadata."""
    url = f"{LISTENBRAINZ_API_URL}/feedback/user/{username}/get-feedback"
    headers = {"Authorization": f"Token {LISTENBRAINZ_TOKEN}"}
    params = {"score": 1, "count": count}
    try:
        resp = requests.get(url, headers=headers, params=params)
        if resp.status_code != 200:
            print(f"❌ Failed to fetch liked tracks: {resp.status_code}")
            return []

        data = resp.json()
        feedback_items = data.get('feedback', [])
        if not feedback_items:
            print("ℹ️ No liked tracks found.")
            return []

        tracks = []
        for item in feedback_items:
            mbid = item.get('recording_mbid')
            if not mbid:
                continue

            # MusicBrainz API (returns both artist and title)
            mb_url = f"https://musicbrainz.org/ws/2/recording/{mbid}"
            mb_headers = {"User-Agent": USER_AGENT}
            mb_params = {"fmt": "json", "inc": "artist-credits"}
            mb_resp = requests.get(mb_url, headers=mb_headers, params=mb_params)

            if mb_resp.status_code != 200:
                continue

            mb_data = mb_resp.json()
            title = mb_data.get('title')
            artist_credit = mb_data.get('artist-credit', [])
            if artist_credit:
                artist = artist_credit[0].get('name')
            else:
                artist = None

            if artist and title:
                tracks.append(f"{artist} - {title}")

        return tracks
    except Exception as e:
        print(f"❌ Error: {e}")
        return []

def play_tracks(tracks):
    """Play a list of search queries using mpv with refined YouTube searches."""
    if not tracks:
        print("No tracks to play.")
        return

    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        for track in tracks:
            clean_track = track.split(' - Topic')[0]
            search_query = f"ytsearch1:{clean_track} Official Audio"
            print(f"🎵 Searching: {clean_track}...")
            try:
                info = ydl.extract_info(search_query, download=False)
                entries = info.get('entries', [])
                if not entries:
                    print(f"  ❌ No results found.")
                    continue
                video = entries[0]
                url = video['url']
                title = video.get('title', track)
                print(f"  ✅ Playing: {title}")
                # Submit now playing & scrobble
                if " - " in clean_track:
                    artist, track_name = clean_track.split(" - ", 1)
                else:
                    artist, track_name = "Unknown", clean_track
                submit_now_playing(artist, track_name)
                subprocess.run(["mpv", "--no-video", url])
                submit_listen(artist, track_name)
            except Exception as e:
                print(f"  ❌ Error: {e}")

# ----------------------------------------------------------------------
# Single track playback (kept for 'play' command)
# ----------------------------------------------------------------------
def search_and_play(query):
    ydl_opts = {"quiet": True, "no_warnings": True, "extract_flat": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(f"ytsearch1:{query}", download=False)
            entries = info.get("entries", [])
            if not entries:
                print(f"No results for '{query}'")
                return
            video = entries[0]
            url = video["url"]
            title = video.get("title", query)
            if " - " in title:
                artist, track = title.split(" - ", 1)
            else:
                artist, track = "Unknown", title
            print(f"🎬 Playing: {title}")
            submit_now_playing(artist, track)
            subprocess.run(["mpv", "--no-video", url])
            submit_listen(artist, track)
        except Exception as e:
            print(f"Error: {e}")

# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="ListenBrainz CLI Music Player")
    subparsers = parser.add_subparsers(dest="command", required=True)

    play_parser = subparsers.add_parser("play", help="Search and play a track")
    play_parser.add_argument("query", nargs="+", help="Search query")

    scrobble_parser = subparsers.add_parser("scrobble", help="Scrobble a track")
    scrobble_parser.add_argument("artist")
    scrobble_parser.add_argument("title")

    np_parser = subparsers.add_parser("nowplaying", help="Set now playing")
    np_parser.add_argument("artist")
    np_parser.add_argument("title")

    playlist_parser = subparsers.add_parser("playlist", help="Play a ListenBrainz playlist by MBID or URL")
    playlist_parser.add_argument("mbid_or_url", help="Playlist UUID or full URL")

    weekly_play_parser = subparsers.add_parser("weekly-play", help="Play your latest weekly jams")
    weekly_play_parser.add_argument("username", nargs="?", help="ListenBrainz username (defaults to 'mobsenpai')")

    liked_parser = subparsers.add_parser("liked", help="Play your liked (loved) tracks")
    liked_parser.add_argument("username", nargs="?", help="ListenBrainz username (defaults to 'mobsenpai')")

    args = parser.parse_args()

    if args.command == "play":
        query = " ".join(args.query)
        search_and_play(query)
    elif args.command == "scrobble":
        submit_listen(args.artist, args.title)
    elif args.command == "nowplaying":
        submit_now_playing(args.artist, args.title)
    elif args.command == "playlist":
        tracks = get_playlist_tracks(args.mbid_or_url)
        if tracks:
            play_tracks(tracks)
    elif args.command == "weekly-play":
        username = args.username or "mobsenpai"
        mbid = get_latest_weekly_jams_mbid(username)
        if mbid:
            tracks = get_playlist_tracks(mbid)
            if tracks:
                play_tracks(tracks)
    elif args.command == "liked":
        username = args.username or "mobsenpai"
        tracks = get_liked_tracks(username)
        if tracks:
            print(f"❤️ Playing {len(tracks)} liked tracks...")
            play_tracks(tracks)
        else:
            print("No liked tracks found.")

if __name__ == "__main__":
    main()
