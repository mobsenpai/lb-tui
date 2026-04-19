import os

# ListenBrainz API configuration
LISTENBRAINZ_API_URL = "https://api.listenbrainz.org/1"
USER_AGENT = "LB-CLI-Player/2.0"

# Read from environment (set by .env or manually)
LISTENBRAINZ_TOKEN = os.environ.get("LISTENBRAINZ_TOKEN")
DEFAULT_USERNAME = os.environ.get("LB_USERNAME")

# Cache file for MBID lookups
CACHE_FILE = os.path.expanduser("~/.cache/lb_mbid_cache.json")

# Hardcoded weekly jams MBID (specific to mobsenpai; others can override)
WEEKLY_JAMS_MBID = "2b85e1a1-3f4f-4eb2-8abb-bbae2a01fcf6"

# Validation warnings (helpful during development)
if not LISTENBRAINZ_TOKEN:
    print("⚠️  LISTENBRAINZ_TOKEN is not set. Scrobbling and API calls will fail.")
if not DEFAULT_USERNAME:
    print("⚠️  LB_USERNAME is not set. Playlist/liked features won't work.")
