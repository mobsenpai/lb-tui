import argparse
from .api import submit_listen, submit_now_playing, get_playlist_tracks, get_liked_tracks, get_weekly_tracks
from .player import search_and_play, play_tracks

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

    weekly_play_parser = subparsers.add_parser("weekly", help="Play your latest weekly jams")
    liked_parser = subparsers.add_parser("liked", help="Play your liked (loved) tracks")

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
    elif args.command == "weekly":
        tracks = get_weekly_tracks()
        if tracks:
            play_tracks(tracks)
        else:
            print("No weekly jams found.")
    elif args.command == "liked":
        tracks = get_liked_tracks()
        if tracks:
            print(f"❤️ Playing {len(tracks)} liked tracks...")
            play_tracks(tracks)
        else:
            print("No liked tracks found.")

if __name__ == "__main__":
    main()
