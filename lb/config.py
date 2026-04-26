"""Configuration loader with credential persistence."""
import os
import json
from pathlib import Path

# --- ListenBrainz API configuration ---
LISTENBRAINZ_API_URL = "https://api.listenbrainz.org/1"
USER_AGENT = "LB-CLI-Player/2.0"

# Cache and playlist defaults
CACHE_FILE = os.path.expanduser("~/.cache/lb_mbid_cache.json")
WEEKLY_JAMS_MBID = "2b85e1a1-3f4f-4eb2-8abb-bbae2a01fcf6"
SCROBBLE_THRESHOLD = 30  # change to 0 to disable threshold

# --- Credential persistence ---
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "lb-tui"
CONFIG_FILE = CONFIG_DIR / "config.json"


def _load_config():
    """Load saved credentials from config file, returning a dict."""
    if not CONFIG_FILE.exists():
        return {}
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_config(data):
    """Save credentials dict to config file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _get_credentials():
    """
    Return (token, username).

    Priority: environment variables > config file > interactive prompt.
    If the user enters credentials interactively, they are saved to the config file.
    """
    token = os.environ.get("LISTENBRAINZ_TOKEN")
    username = os.environ.get("LB_USERNAME")

    # Both provided via environment — nothing else needed
    if token and username:
        return token, username

    # Check the persistent config file
    saved = _load_config()
    if token is None:
        token = saved.get("token")
    if username is None:
        username = saved.get("username")

    # Both available from file
    if token and username:
        return token, username

    # --- Interactive prompt ---
    print("\n" + "=" * 60)
    print("  First-time setup: ListenBrainz credentials")
    print("=" * 60)
    print("You can find your API token at:")
    print("  https://listenbrainz.org/profile/  →  \"User token\"\n")

    try:
        from prompt_toolkit.shortcuts import prompt as pt_prompt
    except ImportError:
        pt_prompt = input  # fallback if prompt_toolkit isn't available

    if not token:
        token = pt_prompt("ListenBrainz Token: ").strip()
    if not username:
        username = pt_prompt("ListenBrainz Username: ").strip()

    if token and username:
        saved["token"] = token
        saved["username"] = username
        _save_config(saved)
        print(f"\n✅ Credentials saved to {CONFIG_FILE}\n")
        return token, username

    # User didn't provide credentials — app will still launch but API calls will fail
    print("\n⚠️  No credentials provided. Scrobbling and liked tracks will not work.\n")
    return token or "", username or ""


# Populate the module-level globals that the rest of the app uses
LISTENBRAINZ_TOKEN, DEFAULT_USERNAME = _get_credentials()

# Validation warnings
if not LISTENBRAINZ_TOKEN:
    print("⚠️  LISTENBRAINZ_TOKEN is not set. Scrobbling and API calls will fail.")
if not DEFAULT_USERNAME:
    print("⚠️  LB_USERNAME is not set. Playlist/liked features won't work.")
