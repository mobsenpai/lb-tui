# lb-cli

A CLI/TUI music player that streams from YouTube and syncs with ListenBrainz.

## Features
- Play any song by searching YouTube (`lb play "Artist Song"`)
- Scrobble listens and "now playing" to ListenBrainz
- Play your liked tracks (`lb liked`)
- Play your weekly jams (`lb weekly`)
- Interactive TUI with playlist browsing, shuffle, and playback controls (`lb-tui`)

## Quick Start (Nix)
```bash
git clone https://github.com/yourusername/lb-cli
cd lb-cli
cp .env.template .env
# Edit .env with your ListenBrainz token and username
nix develop
lb play "Kendrick Lamar HUMBLE"

## Without Nix
bash
pip install .
lb play "Artist Song"
Make sure you have mpv installed on your system.

## Environment Variables
Create a .env file with:
LISTENBRAINZ_TOKEN – your API token
LB_USERNAME – your ListenBrainz username
