"""Portable, sanitized recorded screens; independent of local live evidence."""
import json
from pathlib import Path


def recorded_screen(name):
    # Return fresh dictionaries because emulator tests intentionally modify them.
    fixtures = json.loads((Path(__file__).parent / "fixtures" / "terminal-screens.json").read_text())
    return fixtures[name]
