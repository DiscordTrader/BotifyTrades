import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["PYTHONIOENCODING"] = "utf-8"

from gui_app.chat_assistant import get_response

print("=== Test 1: 'what happened with UNH trade' ===")
r = get_response("what happened with UNH trade")
print(f"Topic: {r.get('topic')} | AI: {r.get('ai_powered', False)}")
print(r.get('response', '')[:400])
print()

print("=== Test 2: 'list down the channels configured in bot' ===")
r = get_response("list down the channels configured in bot")
print(f"Topic: {r.get('topic')} | AI: {r.get('ai_powered', False)}")
print(r.get('response', '')[:400])
print()

print("=== Test 3: 'how many channels are configured' ===")
r = get_response("how many channels are configured")
print(f"Topic: {r.get('topic')} | AI: {r.get('ai_powered', False)}")
print(r.get('response', '')[:400])
