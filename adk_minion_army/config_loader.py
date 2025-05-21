import os

def get_gemini_api_key():
    # Matches existing logic: GEMINI_API_KEY_LEGION
    return os.getenv("GEMINI_API_KEY_LEGION")

def load_minion_agent_config(minion_id: str = "minion_alpha"):
    # In future, this will read from system_configs/config.toml
    # For now, return placeholder data:
    return {
        "minion_id": minion_id,
        "name": f"ADKMinion-{minion_id}",
        "personality_traits_str": "Efficient, Helpful, ADK-Powered"
    }
