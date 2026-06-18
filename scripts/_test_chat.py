import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["PYTHONIOENCODING"] = "utf-8"

from gui_app.chat_assistant import get_response

queries = [
    "what happened with SDOT trade",
    "show me botify-test channel settings",
    "how many channels are configured",
]

for q in queries:
    print(f"Q: {q}")
    print("-" * 60)
    result = get_response(q)
    print(f"AI: {result.get('ai_powered', False)} | Type: {result.get('topic', 'ai')}")
    resp = result.get('response', '')
    print(resp[:500])
    print("=" * 60)
    print()
