import os
import signal
import subprocess
import yt_dlp
from .api import submit_now_playing, submit_listen

def search_url(track):
    """Get YouTube URL for a track."""
    clean = track.split(' - Topic')[0]
    query = f"ytsearch1:{clean} Official Audio"
    with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
        try:
            info = ydl.extract_info(query, download=False)
            entries = info.get('entries', [])
            if entries:
                return entries[0]['webpage_url']
        except Exception:
            pass
    return None

def search_and_play(query):
    """Search YouTube and play the first result with mpv."""
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

            # Start mpv in a new process group so Ctrl+C kills it cleanly
            proc = subprocess.Popen(
                ["mpv", "--no-video", url],
                preexec_fn=os.setsid,
            )
            try:
                proc.wait()
            except KeyboardInterrupt:
                print("\n⏹️ Stopping playback...")
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                proc.wait()
            submit_listen(artist, track)
        except Exception as e:
            print(f"Error: {e}")

def play_tracks(tracks):
    """Play a list of tracks sequentially."""
    if not tracks:
        print("No tracks to play.")
        return

    url_cache = {}
    for track in tracks:
        clean = track.split(' - Topic')[0]
        print(f"🎵 Searching: {clean}...")

        if track in url_cache:
            url = url_cache[track]
        else:
            url = search_url(track)
            if url:
                url_cache[track] = url
            else:
                print(f"  ❌ No results found.")
                continue

        if " - " in clean:
            artist, title = clean.split(" - ", 1)
        else:
            artist, title = "Unknown", clean

        print(f"  ✅ Playing: {clean}")
        submit_now_playing(artist, title)

        proc = subprocess.Popen(
            ["mpv", "--no-video", url],
            preexec_fn=os.setsid,
        )
        try:
            proc.wait()
        except KeyboardInterrupt:
            print("\n⏹️ Stopping...")
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait()
            break

        submit_listen(artist, title)
