import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["PYTHONIOENCODING"] = "utf-8"

from gui_app.config_service import get_ai_provider
from gui_app.broker_credentials_service import get_api_keys_extended

provider = get_ai_provider()
keys = get_api_keys_extended()

print("AI Provider:", provider)
print("OpenAI key:", "SET" if keys.get("openai") else "MISSING")
print("Anthropic key:", "SET" if keys.get("anthropic") else "MISSING")
print("Gemini key:", "SET" if keys.get("gemini") else "MISSING")
print("OPENAI_API_KEY env:", "SET" if os.environ.get("OPENAI_API_KEY") else "MISSING")
print("ANTHROPIC_API_KEY env:", "SET" if os.environ.get("ANTHROPIC_API_KEY") else "MISSING")
print("GEMINI_API_KEY env:", "SET" if os.environ.get("GEMINI_API_KEY") else "MISSING")
