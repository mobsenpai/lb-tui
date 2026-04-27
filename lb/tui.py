#!/usr/bin/env python3
"""
ListenBrainz TUI Music Player
Vim keys, tabs with borders, persistent playback, in‑playlist filter, search results.
"""

import os, sys, subprocess, threading, random, signal, time, json, socket

from prompt_toolkit import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout, HSplit, VSplit, Window, FormattedTextControl
from prompt_toolkit.layout.containers import ConditionalContainer
from prompt_toolkit.widgets import Frame, Label, TextArea
from prompt_toolkit.styles import Style
from prompt_toolkit.filters import Condition
from prompt_toolkit.layout.screen import Point

from .api import (
    get_playlist_tracks,
    get_liked_tracks,
    get_weekly_tracks,
    get_weekly_exploration_tracks,
    get_user_playlists,
    submit_now_playing,
    submit_listen,
    clear_now_playing,
)
from .player import search_track_info, search_url, search_tracks
from .config import SCROBBLE_THRESHOLD


class MusicTUI:
    def __init__(self):
        self.queue = []
        self.current_index = -1
        self.selected_index = 0
        self.shuffle_mode = False
        self.url_cache = {}
        self.mpv_process = None
        self.is_playing = False
        self.all_tracks = []

        self.status_text = "Ready"
        self.now_playing = "Nothing playing"
        self.typing = False

        self.tabs = ["Liked", "Weekly Jams", "Weekly Explor.", "Search", "Playlist"]
        self.active_tab = 0

        self.playlists = []
        self.viewing_playlists = False

        self.filter_text = None
        self.filtered_indices = []

        self._build_ui()
        self._setup_keybindings()

    # ------------------------------------------------------------------
    #  UI Construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        # Tab bar
        self.tab_labels = []
        for i in range(len(self.tabs)):
            self.tab_labels.append(Label(text=""))
        self.tab_frame = Frame(
            title="Tabs",
            body=VSplit(self.tab_labels, padding=0),
        )

        # Queue display
        self.track_list_control = FormattedTextControl(
            text=self._get_formatted_content,
            focusable=False,
            get_cursor_position=self._get_track_cursor_position,
        )
        self.track_list_window = Window(
            content=self.track_list_control,
            always_hide_cursor=True,
            cursorline=False,
            wrap_lines=False,
        )
        self.queue_frame = Frame(
            title="Queue (0 tracks)",
            body=self.track_list_window,
        )

        # Now‑playing – fixed height 1
        self.np_control = FormattedTextControl(
            text=self._get_now_playing_text,
            focusable=False,
        )
        self.now_playing_window = Window(
            content=self.np_control,
            wrap_lines=False,
            height=1,
        )
        self.now_playing_frame = Frame(
            title="Now Playing",
            body=self.now_playing_window,
        )

        # Status line
        self.status_label = Label(text=self.status_text)
        self.mode_label = Label(text="Shuffle: OFF")

        # Help line
        self.help_label = Label(
            text="j/k:nav  Enter:play  / = search/filter  p:pause  n:next  b:prev  s:shuffle  : = cmd  q:quit",
            dont_extend_height=True,
        )

        # Command / filter input (shown when typing and not search tab)
        self.command_input = TextArea(height=1, prompt=": ", multiline=False)
        self._show_command = Condition(
            lambda: self.typing and self.active_tab != 3
        )

        # Search input (tab 3)
        self.tab_input = TextArea(height=1, prompt="Query: ", multiline=False)
        self.tab_input.accept_handler = self._handle_tab_input
        self._show_tab_input = Condition(
            lambda: self.typing and self.active_tab == 3
        )

        root = HSplit([
            self.tab_frame,
            self.now_playing_frame,
            self.queue_frame,
            VSplit([self.status_label, self.mode_label]),
            self.help_label,
            ConditionalContainer(content=self.command_input, filter=self._show_command),
            ConditionalContainer(content=self.tab_input, filter=self._show_tab_input),
        ])
        self.layout = Layout(root)

    def _format_tab(self, idx):
        name = self.tabs[idx]
        if idx == self.active_tab:
            return f"[ {idx+1} {name} ]"
        return f"  {idx+1} {name}  "

    def _get_now_playing_text(self):
        return [("class:bold", self.now_playing)]

    # ------------------------------------------------------------------
    #  Text generation (search placeholder, filtering)
    # ------------------------------------------------------------------
    def _get_formatted_content(self):
        if self.viewing_playlists:
            return self._format_playlists()

        # Show placeholder on empty search tab
        if self.active_tab == 3 and not self.queue:
            return [("", "Type a query and press Enter\n")]

        return self._format_tracks()

    def _format_tracks(self):
        if self.filter_text:
            self.filtered_indices = [
                i for i, track in enumerate(self.queue)
                if self.filter_text.lower() in track.lower()
            ]
        else:
            self.filtered_indices = []

        indices = self.filtered_indices if self.filter_text else range(len(self.queue))
        lines = []
        for display_idx, real_idx in enumerate(indices):
            track = self.queue[real_idx]
            cursor = ">" if display_idx == self.selected_index else " "
            style = "bold" if real_idx == self.current_index else ""
            lines.append((f"class:{style}", f"{cursor} {track[:80]}\n"))

        if not lines:
            if self.filter_text:
                lines.append(("", "No matching tracks\n"))
            else:
                lines.append(("", "No tracks\n"))
        return lines

    def _format_playlists(self):
        lines = []
        for i, (title, _) in enumerate(self.playlists):
            cursor = ">" if i == self.selected_index else " "
            lines.append(("", f"{cursor} {title[:80]}\n"))
        if not lines:
            lines.append(("", "No playlists found\n"))
        return lines

    def _get_track_cursor_position(self):
        items = self.playlists if self.viewing_playlists else self.queue
        if self.filter_text:
            items = self.filtered_indices
        if items and 0 <= self.selected_index < len(items):
            return Point(x=0, y=self.selected_index)
        return None

    # ------------------------------------------------------------------
    #  UI update (dynamic titles)
    # ------------------------------------------------------------------
    def _update_ui(self):
        self.status_label.text = self.status_text
        self.mode_label.text = f"Shuffle: {'ON' if self.shuffle_mode else 'OFF'}"

        if self.viewing_playlists:
            self.queue_frame.title = f"Playlists ({len(self.playlists)})"
        elif self.active_tab == 3:
            if self.queue:
                self.queue_frame.title = f"Search Results ({len(self.queue)} tracks)"
            else:
                self.queue_frame.title = "Search"
        elif self.filter_text:
            self.queue_frame.title = f"Filtered: {self.filter_text} ({len(self.filtered_indices)}/{len(self.queue)} tracks)"
        else:
            self.queue_frame.title = f"Queue ({len(self.queue)} tracks)"

        for i, lbl in enumerate(self.tab_labels):
            lbl.text = self._format_tab(i)
            lbl.style = "bold" if i == self.active_tab else ""

        if self.app:
            self.app.invalidate()

    def _safe_update_ui(self):
        if hasattr(self, 'app') and self.app and self.app.loop:
            if threading.current_thread() is threading.main_thread():
                self._update_ui()
            else:
                self.app.loop.call_soon_threadsafe(self._update_ui)
        else:
            self._update_ui()

    # ------------------------------------------------------------------
    #  Typing mode
    # ------------------------------------------------------------------
    def _enter_typing(self, widget, prompt, callback, set_filter_mode=False):
        """Activate a text input widget – disable shortcuts."""
        self.typing = True
        self.filter_mode = set_filter_mode
        widget.text = ""
        widget.prompt = prompt
        widget.accept_handler = callback
        try:
            self.app.layout.focus(widget)
        except:
            pass
        self._update_ui()

    def _exit_typing(self):
        """Deactivate typing – re‑enable shortcuts."""
        self.typing = False
        self.filter_mode = False
        # Clear both input buffers
        self.command_input.text = ""
        self.tab_input.text = ""
        try:
            self.app.layout.focus(self.track_list_window)
        except:
            pass
        self._update_ui()

    # ------------------------------------------------------------------
    #  Command / filter starters
    # ------------------------------------------------------------------
    def _start_command(self):
        self._enter_typing(self.command_input, ": ", self._handle_command)

    def _start_filter(self):
        # In search tab, `/` re‑enters search query instead of filter
        if self.active_tab == 3:
            self._start_search()
            return
        self._enter_typing(self.command_input, "filter: ", self._handle_filter, set_filter_mode=True)

    # ------------------------------------------------------------------
    #  Command handling
    # ------------------------------------------------------------------
    def _handle_command(self, buffer):
        text = buffer.text.strip()
        buffer.text = ""
        self._exit_typing()
        if not text:
            return
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd in ("play", "p"):
            if arg:
                self._cmd_play_immediately(arg)
            else:
                self.status_text = "Usage: play <query>"
        elif cmd == "liked":
            self._load_playlist("liked")
        elif cmd == "weekly":
            self._load_playlist("weekly")
        elif cmd == "weeklyexpl":
            self._load_playlist("weekly_exploration")
        elif cmd == "playlist":
            if arg:
                self._load_playlist("playlist", arg)
            else:
                self.status_text = "Usage: playlist <mbid>"
        elif cmd == "filter":
            self._apply_filter(arg)
        elif cmd == "clear":
            self.clear_queue()
        elif cmd in ("pause", "stop"):
            self.toggle_pause()
        elif cmd in ("next", "n"):
            self.next_track()
        elif cmd in ("prev", "b"):
            self.prev_track()
        elif cmd in ("shuffle", "s"):
            self.toggle_shuffle()
        elif cmd in ("quit", "q", "exit"):
            self._quit()
        else:
            self.status_text = f"Unknown command: {cmd}"
        self._safe_update_ui()

    def _handle_filter(self, buffer):
        text = buffer.text.strip()
        buffer.text = ""
        self._apply_filter(text)
        self._exit_typing()

    def _apply_filter(self, text):
        if text:
            self.filter_text = text
        else:
            self.filter_text = None
        self.selected_index = 0
        self._safe_update_ui()

    # ------------------------------------------------------------------
    #  Search tab
    # ------------------------------------------------------------------
    def _start_search(self):
        """Enter search query mode."""
        self._enter_typing(self.tab_input, "Query: ", self._handle_tab_input)

    def _handle_tab_input(self, buffer):
        text = buffer.text.strip()
        buffer.text = ""
        self._exit_typing()
        if text:
            self._cmd_search_list(text)

    def _cmd_search_list(self, query):
        self.status_text = f"Searching: {query}..."
        self._safe_update_ui()
        results = search_tracks(query, limit=10)
        if results:
            self.queue.clear()
            for title, url in results:
                self.queue.append(title)
                self.url_cache[title] = url
            self.all_tracks = list(self.queue)
            self.current_index = -1
            self.selected_index = 0
            self.now_playing = "Nothing playing"
            self.status_text = f"Found {len(results)} results for '{query}'"
        else:
            self.status_text = f"No results for: {query}"
        self._safe_update_ui()

    # ------------------------------------------------------------------
    #  Tab switching (playback preserved)
    # ------------------------------------------------------------------
    def _activate_tab(self, idx):
        self.active_tab = idx
        self._apply_filter(None)
        self._exit_typing()               # ensure typing mode off

        if idx == 0:
            self._load_playlist("liked")
        elif idx == 1:
            self._load_playlist("weekly")
        elif idx == 2:
            self._load_playlist("weekly_exploration")
        elif idx == 3:
            # Clear old queue and show search prompt
            self.queue.clear()
            self.all_tracks = []
            if not self.is_playing:
                self.current_index = -1
                self.now_playing = "Nothing playing"
            self.selected_index = 0
            self._safe_update_ui()
            self._start_search()           # prompt appears
        elif idx == 4:
            self._fetch_and_show_playlists()

    # ------------------------------------------------------------------
    #  Playlist browser
    # ------------------------------------------------------------------
    def _fetch_and_show_playlists(self):
        self.status_text = "Fetching playlists..."
        self._safe_update_ui()
        try:
            self.playlists = get_user_playlists()
            self.viewing_playlists = True
            self.queue.clear()
            self.all_tracks = []
            self.current_index = -1
            self.selected_index = 0
            self._apply_filter(None)
            self.status_text = f"Found {len(self.playlists)} playlists"
        except Exception as e:
            self.status_text = f"Error: {e}"
            self.playlists = []
            self.viewing_playlists = False
        self._safe_update_ui()

    def _load_selected_playlist(self):
        if not self.viewing_playlists or not self.playlists:
            return
        idx = self.selected_index
        if idx < 0 or idx >= len(self.playlists):
            return
        _, mbid = self.playlists[idx]
        self.status_text = "Loading playlist..."
        self._safe_update_ui()
        try:
            tracks = get_playlist_tracks(mbid)
            self.viewing_playlists = False
            self.queue = []
            self.all_tracks = []
            self.current_index = -1
            self.selected_index = 0
            self._apply_filter(None)
            if tracks:
                for t in tracks:
                    if t not in self.queue:
                        self.queue.append(t)
                self.all_tracks = list(self.queue)
                self.status_text = f"Loaded {len(tracks)} tracks"
            else:
                self.status_text = "Playlist empty"
        except Exception as e:
            self.status_text = f"Error: {e}"
            self.viewing_playlists = False
        self._safe_update_ui()

    # ------------------------------------------------------------------
    #  Loading playlists (no autoplay)
    # ------------------------------------------------------------------
    def _load_playlist(self, ptype, identifier=None):
        from .config import LISTENBRAINZ_TOKEN, DEFAULT_USERNAME

        if ptype in ("liked", "weekly", "weekly_exploration"):
            if not DEFAULT_USERNAME:
                self.status_text = "❌ LB_USERNAME not set."
                self._safe_update_ui()
                return
            if not LISTENBRAINZ_TOKEN:
                self.status_text = "❌ LISTENBRAINZ_TOKEN not set."
                self._safe_update_ui()
                return

        self.status_text = f"Loading {ptype}..."
        self._safe_update_ui()
        try:
            if ptype == "liked":
                tracks = get_liked_tracks()
            elif ptype == "weekly":
                tracks = get_weekly_tracks()
            elif ptype == "weekly_exploration":
                tracks = get_weekly_exploration_tracks()
            elif ptype == "playlist":
                tracks = get_playlist_tracks(identifier)
            else:
                tracks = []
        except Exception as e:
            self.status_text = f"Error: {e}"
            self._safe_update_ui()
            return

        self.queue.clear()
        self.all_tracks = []
        if not self.is_playing:
            self.current_index = -1
            self.now_playing = "Nothing playing"
        self.selected_index = 0
        self.url_cache.clear()
        self._apply_filter(None)

        if tracks:
            for t in tracks:
                if t not in self.queue:
                    self.queue.append(t)
            self.all_tracks = list(self.queue)
            self.status_text = f"Loaded {len(tracks)} tracks"
        else:
            self.status_text = f"No tracks found for {ptype}"

        self.viewing_playlists = False
        self._safe_update_ui()

    def _cmd_load_playlist(self, ptype, identifier=None):
        self._load_playlist(ptype, identifier)

    # ------------------------------------------------------------------
    #  Playback controls
    # ------------------------------------------------------------------
    def _stop_playback(self):
        if self.mpv_process:
            self.mpv_process.terminate()
            self.mpv_process = None
        self.is_playing = False
        socket_path = "/tmp/lb-mpv-socket"
        if os.path.exists(socket_path):
            os.remove(socket_path)

    def _play_url(self, url, title=None):
        self._stop_playback()
        cmd = ["mpv", "--no-video", "--input-ipc-server=/tmp/lb-mpv-socket"]
        if title:
            cmd.append(f"--force-media-title={title}")
        cmd.append(url)
        self.mpv_process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid,
        )
        self.is_playing = True

    def play_index(self, display_idx):
        if self.filter_text and self.filtered_indices:
            if 0 <= display_idx < len(self.filtered_indices):
                real_idx = self.filtered_indices[display_idx]
            else:
                return
        else:
            real_idx = display_idx
            if not (0 <= real_idx < len(self.queue)):
                return

        self.current_index = real_idx
        self.selected_index = display_idx
        track = self.queue[real_idx]
        url = self.url_cache.get(track) or search_url(track)
        if url:
            self.url_cache[track] = url
            self.now_playing = track
            self._play_url(url, title=track)
            self.status_text = "Playing"

            if " - " in track:
                artist, title = track.split(" - ", 1)
            else:
                artist, title = "Unknown", track
            submit_now_playing(artist, title)

            start_time = time.monotonic()
            threading.Thread(
                target=self._monitor_playback,
                args=(real_idx, track, start_time),
                daemon=True,
            ).start()
        else:
            self.status_text = f"Not found: {track}"
            self.next_track()
        self._safe_update_ui()

    def _monitor_playback(self, for_index, track, start_time):
        if self.mpv_process:
            self.mpv_process.wait()
            if self.current_index == for_index:
                self.is_playing = False
                self.status_text = "Stopped"

                elapsed = time.monotonic() - start_time
                if elapsed >= SCROBBLE_THRESHOLD:
                    if " - " in track:
                        artist, title = track.split(" - ", 1)
                    else:
                        artist, title = "Unknown", track
                    try:
                        submit_listen(artist, title)
                        self.status_text = "Scrobbled"
                    except Exception as e:
                        self.status_text = f"Scrobble failed: {e}"
                else:
                    self.status_text = "Skipped (too short)"

                self._safe_update_ui()
                self.next_track()

    def next_track(self):
        if not self.queue:
            return
        if self.filter_text and self.filtered_indices:
            if self.current_index in self.filtered_indices:
                pos = self.filtered_indices.index(self.current_index)
                nxt_display = (pos + 1) % len(self.filtered_indices)
            else:
                nxt_display = 0
            self.play_index(nxt_display)
        else:
            nxt = (self.current_index + 1) % len(self.queue)
            self.play_index(nxt)

    def prev_track(self):
        if not self.queue:
            return
        if self.filter_text and self.filtered_indices:
            if self.current_index in self.filtered_indices:
                pos = self.filtered_indices.index(self.current_index)
                prv_display = (pos - 1) % len(self.filtered_indices)
            else:
                prv_display = 0
            self.play_index(prv_display)
        else:
            prv = (self.current_index - 1) % len(self.queue)
            self.play_index(prv)

    def toggle_pause(self):
        if not self.mpv_process or self.mpv_process.poll() is not None:
            return
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect("/tmp/lb-mpv-socket")                         
            s.sendall(json.dumps({"command": ["cycle", "pause"]}).encode() + b"\n")
            s.close()
        except Exception:
            return                                                 
    
        self.is_playing = not self.is_playing
        self.status_text = "Paused" if not self.is_playing else "Playing"
        self._safe_update_ui()

    def toggle_shuffle(self):
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
        self._apply_filter(None)
        self._safe_update_ui()

    # ------------------------------------------------------------------
    #  Queue management
    # ------------------------------------------------------------------
    def add_to_queue(self, track_name):
        self.queue.append(track_name)
        self.all_tracks = list(self.queue)
        self._safe_update_ui()
        if not self.is_playing and self.mpv_process is None:
            self.play_index(len(self.queue) - 1)

    def clear_queue(self):
        self._stop_playback()
        self.queue.clear()
        self.all_tracks = []
        self.current_index = -1
        self.selected_index = 0
        self.url_cache.clear()
        self.now_playing = "Nothing playing"
        self.status_text = "Ready"
        self._apply_filter(None)
        self._safe_update_ui()

    # ------------------------------------------------------------------
    #  Play immediately (for :play)
    # ------------------------------------------------------------------
    def _cmd_play_immediately(self, query):
        self.status_text = f"Searching: {query}..."
        self._safe_update_ui()
        url, title = search_track_info(query)
        if url:
            self._stop_playback()
            self.queue.insert(0, title)
            self.all_tracks = list(self.queue)
            self.url_cache[title] = url
            self.selected_index = 0
            self.play_index(0)
        else:
            self.status_text = f"No results for: {query}"
            self._safe_update_ui()

    # ------------------------------------------------------------------
    #  Quit
    # ------------------------------------------------------------------
    def _quit(self):
        self._stop_playback()
        clear_now_playing()
        if self.app:
            self.app.exit()

    # ------------------------------------------------------------------
    #  Keybindings (all disabled while typing)
    # ------------------------------------------------------------------
    def _setup_keybindings(self):
        self.kb = KeyBindings()
        idle = Condition(lambda: not self.typing)

        @self.kb.add('q', filter=idle)
        def _(event):
            self._quit()

        @self.kb.add(':', filter=idle)
        def _(event):
            self._start_command()

        @self.kb.add('/', filter=idle)
        def _(event):
            self._start_filter()

        @self.kb.add('escape', filter=Condition(lambda: self.typing))
        def _(event):
            self._exit_typing()

        # Navigation
        @self.kb.add('j', filter=idle)
        @self.kb.add('down', filter=idle)
        def _(event):
            items = self.playlists if self.viewing_playlists else self.queue
            if self.filter_text:
                items = self.filtered_indices
            if items:
                self.selected_index = (self.selected_index + 1) % len(items)
                self._safe_update_ui()

        @self.kb.add('k', filter=idle)
        @self.kb.add('up', filter=idle)
        def _(event):
            items = self.playlists if self.viewing_playlists else self.queue
            if self.filter_text:
                items = self.filtered_indices
            if items:
                self.selected_index = (self.selected_index - 1) % len(items)
                self._safe_update_ui()

        @self.kb.add('enter', filter=idle)
        def _(event):
            if self.viewing_playlists:
                self._load_selected_playlist()
            else:
                # On empty search tab, Enter can re‑open search prompt
                if self.active_tab == 3 and not self.queue:
                    self._start_search()
                    return
                items = self.filtered_indices if self.filter_text else self.queue
                if items and 0 <= self.selected_index < len(items):
                    self.play_index(self.selected_index)

        # Playback controls
        @self.kb.add('p', filter=idle)
        @self.kb.add('space', filter=idle)
        def _(event):
            self.toggle_pause()

        @self.kb.add('s', filter=idle)
        def _(event):
            self.toggle_shuffle()

        @self.kb.add('n', filter=idle)
        def _(event):
            if not self.viewing_playlists:
                self.next_track()

        @self.kb.add('b', filter=idle)
        def _(event):
            if not self.viewing_playlists:
                self.prev_track()

        # Tab keys
        for i, key in enumerate(['1', '2', '3', '4', '5']):
            @self.kb.add(key, filter=idle)
            def _(event, idx=i):
                self._activate_tab(idx)

    # ------------------------------------------------------------------
    def run(self):
        self.app = Application(
            layout=self.layout,
            key_bindings=self.kb,
            full_screen=True,
            style=Style.from_dict({
                'bold': 'bold',
                'input-field': 'bg:#222222 #ffffff',
            }),
        )

        def on_resize(signum, frame):
            if self.app:
                self.app.invalidate()

        try:
            signal.signal(signal.SIGWINCH, on_resize)
        except:
            pass

        self._activate_tab(0)
        self.app.run()


def main():
    print("Starting ListenBrainz TUI...")
    tui = MusicTUI()
    tui.run()


if __name__ == "__main__":
    main()
