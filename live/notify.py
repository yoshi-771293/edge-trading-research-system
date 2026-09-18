"""Alerts. ntfy.sh when state/notify.json has {"ntfy_topic": "..."}; always also a
macOS notification and a row in the journal. No other outbound calls anywhere."""
import json, subprocess
from pathlib import Path
import requests

CONFIG = Path(__file__).resolve().parent.parent / "state" / "notify.json"
CLICK_URL = "https://claude.ai/code"     # tapping a notification opens Claude Code (Remote Control session)


def _topic():
    try:
        return json.loads(CONFIG.read_text()).get("ntfy_topic")
    except Exception:
        return None


def ascii_header(v: str) -> str:
    """HTTP header values must be ASCII; an emoji in a title must never drop an alert."""
    v = v.replace("\u2014", "-").replace("\u2013", "-")
    return " ".join(v.encode("ascii", "ignore").decode().split())


def alert(title: str, msg: str, priority: str = "high") -> bool:
    sent = False
    topic = _topic()
    if topic:
        try:
            requests.post(f"https://ntfy.sh/{topic}", data=msg.encode(), headers={"Title": ascii_header(title), "Priority": priority, "Click": CLICK_URL}, timeout=15)
            sent = True
        except Exception:
            pass
    try:
        subprocess.run(["osascript", "-e", f'display notification "{msg[:200]}" with title "{title}"'], timeout=10)
    except Exception:
        pass
    return sent


def digest(title: str, msg: str) -> bool:
    return alert(title, msg, priority="default")
