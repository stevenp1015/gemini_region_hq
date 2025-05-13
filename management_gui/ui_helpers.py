# management_gui/ui_helpers.py
import json
import sys # Added sys import for stderr
import time
import urllib.parse
from datetime import datetime
from typing import Dict, Any

from nicegui import ui

# Import app_state and GUI_COMMANDER_ID from the new app_state module
# Use relative import
try:
    from .app_state import app_state, GUI_COMMANDER_ID, gui_log
except ImportError:
    # Fallback for potential direct execution or testing?
    print("WARNING: Could not import from .app_state, using placeholder.", file=sys.stderr)
    app_state = {"minions": {}} # Minimal placeholder
    GUI_COMMANDER_ID = "STEVEN_GUI_COMMANDER"
    def gui_log(msg, level="INFO"): print(f"UI_HELPERS_LOG ({level}): {msg}")


# --- UI Styling Constants ---
# Basic mapping for Quasar color names (used in classes like bg-*) to HEX codes for SVG
# This can be expanded as needed.
QUASAR_COLOR_TO_HEX = {
    "blue-2": "#BBDEFB", "blue-5": "#2196F3",
    "red-2": "#FFCDD2", "red-5": "#F44336",
    "green-2": "#C8E6C9", "green-5": "#4CAF50",
    "purple-2": "#E1BEE7", "purple-5": "#9C27B0",
    "orange-2": "#FFE0B2", "orange-5": "#FF9800",
    "teal-2": "#B2DFDB", "teal-5": "#009688",
    "pink-2": "#F8BBD0", "pink-5": "#E91E63",
    "grey-3": "#e0e0e0", "grey-5": "#9e9e9e", # For default/unknown minions
    "black": "#000000",
    "white": "#FFFFFF",
}

MINION_STYLE_PALETTE = [
    {"bubble_class": "bg-red-2 text-black", "avatar_color_name": "red-5"},
    {"bubble_class": "bg-green-2 text-black", "avatar_color_name": "green-5"},
    {"bubble_class": "bg-purple-2 text-black", "avatar_color_name": "purple-5"},
    {"bubble_class": "bg-orange-2 text-black", "avatar_color_name": "orange-5"},
    {"bubble_class": "bg-teal-2 text-black", "avatar_color_name": "teal-5"},
    {"bubble_class": "bg-pink-2 text-black", "avatar_color_name": "pink-5"},
]
# Store assigned styles to keep them consistent for minions during a session
_minion_styles_cache = {}
_next_minion_style_index = 0


# --- Helper function to get formatted minion display name ---
def get_formatted_minion_display(minion_id: str) -> str:
    """Gets the display name for a minion, preferring user_facing_name, then name, then ID."""
    minion_data = app_state["minions"].get(minion_id)
    if minion_data:
        # name_display is already the prioritized user_facing_name, agent_card.name, or minion_id
        name_display = minion_data.get("name_display", minion_id) # Fallback to minion_id if key missing

        # If name_display is not the same as minion_id (meaning it's a friendly name)
        if name_display and name_display != minion_id:
            return f"{name_display} ({minion_id})"
        return name_display # This will be minion_id if it was the only name, or if name_display was None/empty
    return minion_id # Fallback if minion_id not in app_state or minion_data is None


def get_sender_style(sender_id: str) -> Dict[str, Any]:
    """Determines the display style (avatar, color, name) for a given sender ID."""
    global _next_minion_style_index
    if sender_id == GUI_COMMANDER_ID:
        return {
            "avatar_letter": "S",
            "bubble_class": "bg-blue-2 text-black",
            "avatar_color_name": "blue-5",
            "sender_display_name": "STEVEN" # Use a consistent display name for the commander
        }

    # Check app_state for the minion's display name
    minion_info = app_state["minions"].get(sender_id)

    # Use the core friendly name (name_display) for avatar logic
    core_display_name = sender_id # Default to sender_id
    if minion_info and minion_info.get("name_display"):
        core_display_name = minion_info["name_display"]

    # Use the formatted name for display in chat bubbles
    formatted_sender_name = get_formatted_minion_display(sender_id)

    if sender_id not in _minion_styles_cache:
        style_to_assign = MINION_STYLE_PALETTE[_next_minion_style_index % len(MINION_STYLE_PALETTE)]
        _minion_styles_cache[sender_id] = style_to_assign
        _next_minion_style_index += 1

    assigned_style = _minion_styles_cache[sender_id]

    avatar_letter = core_display_name[0].upper() if core_display_name else "?"
    # More robust way to get first char if core_display_name could be empty
    if not core_display_name:
        avatar_letter = sender_id[0].upper() if sender_id else "?"

    return {
        "avatar_letter": avatar_letter,
        "bubble_class": assigned_style["bubble_class"],
        "avatar_color_name": assigned_style["avatar_color_name"],
        "sender_display_name": formatted_sender_name
    }


def generate_circular_avatar_svg(letter: str, avatar_bg_color_name: str, text_color_hex: str = "#FFFFFF", size: int = 32) -> str:
    """Generates a data URI for a circular SVG avatar with a letter."""
    actual_bg_hex_color = QUASAR_COLOR_TO_HEX.get(avatar_bg_color_name, QUASAR_COLOR_TO_HEX.get("grey-5", "#9e9e9e"))

    svg_content = f'''
<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}">
  <circle cx="{size/2}" cy="{size/2}" r="{size/2}" fill="{actual_bg_hex_color}"/>
  <text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle"
        font-family="sans-serif" font-weight="bold" font-size="{size*0.55}px" fill="{text_color_hex}">
    {letter}
  </text>
</svg>
    '''.strip()
    # Use urllib.parse.quote for proper SVG data URI encoding
    return f"data:image/svg+xml;utf8,{urllib.parse.quote(svg_content)}"


async def copy_message_to_clipboard(text: str):
    """Copies the given text to the clipboard using browser's navigator.clipboard API."""
    # json.dumps is crucial for handling special characters in text for JavaScript
    js_command = f"navigator.clipboard.writeText({json.dumps(text)});"
    try:
        # Note: ui.run_javascript requires an active client connection.
        # This function should only be called from a UI event handler.
        await ui.run_javascript(js_command)
        ui.notify("Copied to clipboard!", type='positive', position='top-right', timeout=2000)
    except Exception as e:
        gui_log(f"Failed to copy to clipboard: {e}", level="ERROR")
        try:
            ui.notify("Failed to copy to clipboard.", type='negative', position='top-right', timeout=3000)
        except Exception as notify_err:
            gui_log(f"Failed to show notification for clipboard error: {notify_err}", level="ERROR")

# --- Add other general UI helper functions below as they are identified ---
# Example placeholder:
# def format_timestamp(ts: float) -> str:
#     """Formats a Unix timestamp into a readable string."""
#     if not isinstance(ts, (int, float)) or ts <= 0:
#         return "Invalid Time"
#     try:
#         return datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
#     except Exception:
#         return "Error Formatting Time"