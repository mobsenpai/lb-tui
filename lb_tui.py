#!/usr/bin/env python3
"""
ListenBrainz TUI Music Player (no mpv module required)
"""

import json
import os
import sys
import subprocess
import threading
import time
import random
import tempfile
import signal

from prompt_toolkit import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout, HSplit, VSplit
from prompt_toolkit.widgets import TextArea, Label, Frame
from prompt_toolkit.styles import Style

import yt_dlp
import requests

# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------
LISTENBRAINZ_TOKEN = "ccf7c17f-8fdd-4190-a502-c929137440cb"
LISTENBRAINZ_API_URL = "https://api.listenbrainz.org/1"
USER_AGENT = "LB-CLI-Player/2.0"
CACHE_FILE = os.path.expanduser("~/.cache/lb_mbid_cache.json")

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_cache(cache):
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache, f)

# ----------------------------------------------------------------------
# API Helpers
# ----------------------------------------------------------------------
def get_playlist_tracks(playlist_mbid):
    if playlist_mbid.startswith("http"):
        playlist_mbid = playlist_mbid.split("/")[-1]
    url = f"{LISTENBRAINZ_API_URL}/playlist/{playlist_mbid}"
    headers = {"Authorization": f"Token {LISTENBRAINZ_TOKEN}"}
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

def get_liked_tracks(username, count=500):
    url = f"{LISTENBRAINZ_API_URL}/feedback/user/{username}/get-feedback"
    headers = {"Authorization": f"Token {LISTENBRAINZ_TOKEN}"}
    params = {"score": 1, "count": count}
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

def get_weekly_tracks(username):
    if username == "mobsenpai":
        return get_playlist_tracks("2b85e1a1-3f4f-4eb2-8abb-bbae2a01fcf6")
    return []

# ----------------------------------------------------------------------
# TUI using subprocess mpv
# ----------------------------------------------------------------------
class MusicTUI:
    def __init__(self, tracks, title="Playlist"):
        self.all_tracks = tracks
        self.title = title
        self.queue = list(tracks)
        self.current_index = -1
        self.shuffle_mode = False
        self.url_cache = {}
        self.mpv_process = None
        self.is_playing = False
        self.current_track_url = None

        self.status_text = "Ready"
        self.now_playing = "Nothing playing"
        self.volume = 100
        self.selected_index = 0

        self._build_ui()
        self._bind_keys()

    def _build_ui(self):
        self.track_list_area = TextArea(
            text=self._format_track_list_text(),
            read_only=True,
            focusable=False,
            scrollbar=True,
        )
        self.np_label = Label(text=self.now_playing)
        self.status_label = Label(text=self.status_text)
        self.mode_label = Label(text=f"Shuffle: {'ON' if self.shuffle_mode else 'OFF'}")

        help_text = Label(
            text="↑/↓: navigate  Enter: play  s: shuffle  p: pause  n: next  b: prev  q: quit"
        )

        root_container = HSplit([
            Frame(self.np_label, title="Now Playing"),
            Frame(self.track_list_area, title=f"{self.title} ({len(self.queue)} tracks)"),
            VSplit([self.status_label, self.mode_label]),
            help_text,
        ])
        self.layout = Layout(root_container)

    def _format_track_list_text(self):
        lines = []
        for i, track in enumerate(self.queue):
            prefix = "→ " if i == self.current_index else "  "
            cursor = ">" if i == self.selected_index else " "
            lines.append(f"{cursor}{prefix}{track[:80]}")
        return "\n".join(lines)

    def _update_track_list(self):
        self.track_list_area.text = self._format_track_list_text()

    def _bind_keys(self):
        self.kb = KeyBindings()

        @self.kb.add('q')
        def _(event):
            self._stop_playback()
            event.app.exit()

        @self.kb.add('up')
        def _(event):
            if self.queue:
                self.selected_index = (self.selected_index - 1) % len(self.queue)
                self._update_ui()

        @self.kb.add('down')
        def _(event):
            if self.queue:
                self.selected_index = (self.selected_index + 1) % len(self.queue)
                self._update_ui()

        @self.kb.add('enter')
        def _(event):
            if self.queue:
                self.play_index(self.selected_index)

        @self.kb.add('s')
        def _(event):
            self.shuffle_mode = not self.shuffle_mode
            if self.shuffle_mode:
                if self.current_index >= 0:
                    current = self.queue[self.current_index]
                    rest = self.queue[:self.current_index] + self.queue[self.current_index+1:]
                    random.shuffle(rest)
                    self.queue = [current] + rest
                    self.current_index = 0
                else:
                    random.shuffle(self.queue)
                self.selected_index = 0
            else:
                self.queue = list(self.all_tracks)
                if self.current_index >= 0:
                    current_track = self.queue[self.current_index]
                    try:
                        self.current_index = self.all_tracks.index(current_track)
                    except ValueError:
                        self.current_index = 0
                self.selected_index = self.current_index if self.current_index >= 0 else 0
            self.mode_label.text = f"Shuffle: {'ON' if self.shuffle_mode else 'OFF'}"
            self._update_track_list()
            self._update_ui()

        @self.kb.add('space')
        @self.kb.add('p')
        def _(event):
            self._toggle_pause()

        @self.kb.add('n')
        def _(event):
            self.next_track()

        @self.kb.add('b')
        def _(event):
            self.prev_track()

    def _toggle_pause(self):
        if self.mpv_process and self.mpv_process.poll() is None:
            # Send SIGSTOP to pause, SIGCONT to resume (Unix only)
            if self.is_playing:
                self.mpv_process.send_signal(signal.SIGSTOP)
                self.is_playing = False
                self.status_text = "Paused"
            else:
                self.mpv_process.send_signal(signal.SIGCONT)
                self.is_playing = True
                self.status_text = "Playing"
        self._update_ui()

    def _stop_playback(self):
        if self.mpv_process:
            self.mpv_process.terminate()
            self.mpv_process = None
            self.is_playing = False

    def _update_ui(self):
        self.np_label.text = self.now_playing
        self.status_label.text = self.status_text
        self._update_track_list()
        if hasattr(self, 'app') and self.app:
            self.app.invalidate()

    def _search_url(self, track):
        if track in self.url_cache:
            return self.url_cache[track]
        clean = track.split(' - Topic')[0]
        query = f"ytsearch1:{clean} Official Audio"
        with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
            try:
                info = ydl.extract_info(query, download=False)
                entries = info.get('entries', [])
                if entries:
                    url = entries[0]['webpage_url']
                    self.url_cache[track] = url
                    return url
            except Exception:
                pass
        return None

    def _play_url(self, url):
        self._stop_playback()
        self.mpv_process = subprocess.Popen(
            ["mpv", "--no-video", url],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid,
        )
        self.is_playing = True

    def play_index(self, idx):
        if 0 <= idx < len(self.queue):
            self.current_index = idx
            self.selected_index = idx
            track = self.queue[idx]
            url = self._search_url(track)
            if url:
                self.now_playing = track
                self._play_url(url)
                self.status_text = "Playing"
                # Start a monitor thread for when playback ends
                threading.Thread(target=self._monitor_playback, daemon=True).start()
            else:
                self.status_text = f"Not found: {track}"
                self.next_track()
            self._update_ui()

    def _monitor_playback(self):
        if self.mpv_process:
            self.mpv_process.wait()
            self.is_playing = False
            self.status_text = "Stopped"
            self._update_ui()
            # Auto-advance to next track
            self.next_track()

    def next_track(self):
        if self.queue:
            nxt = (self.current_index + 1) % len(self.queue)
            self.play_index(nxt)

    def prev_track(self):
        if self.queue:
            prv = (self.current_index - 1) % len(self.queue)
            self.play_index(prv)

    def run(self):
        self.app = Application(
            layout=self.layout,
            key_bindings=self.kb,
            full_screen=True,
            style=Style.from_dict({'frame.label': 'bold'}),
        )
        self.app.run()

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    if len(sys.argv) < 2:
        print("Usage: lb_tui.py liked [username]")
        print("       lb_tui.py weekly [username]")
        print("       lb_tui.py playlist <mbid_or_url>")
        sys.exit(1)

    cmd = sys.argv[1]
    username = sys.argv[2] if len(sys.argv) > 2 else "mobsenpai"

    print("Loading tracks...")
    if cmd == "liked":
        tracks = get_liked_tracks(username)
        title = f"Liked Songs ({username})"
    elif cmd == "weekly":
        tracks = get_weekly_tracks(username)
        title = f"Weekly Jams ({username})"
    elif cmd == "playlist":
        if len(sys.argv) < 3:
            print("Playlist MBID required")
            sys.exit(1)
        tracks = get_playlist_tracks(sys.argv[2])
        title = f"Playlist {sys.argv[2][:8]}..."
    else:
        print("Unknown command")
        sys.exit(1)

    if not tracks:
        print("No tracks found.")
        sys.exit(1)

    print(f"Loaded {len(tracks)} tracks. Launching TUI...")
    tui = MusicTUI(tracks, title)
    tui.run()

if __name__ == "__main__":
    main()
