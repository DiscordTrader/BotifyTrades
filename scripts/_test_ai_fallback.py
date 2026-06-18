import sys, os, asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["PYTHONIOENCODING"] = "utf-8"

async def test():
    from src.services.ai_signal_parser import parse_signal_with_ai

    signal = "UNH   397.5C at 8.5 for  6/12\nTargets 9/11.5/14.5\nSL 3.75"
    print(f"Testing AI fallback with: {signal.split(chr(10))[0]}")
    print()

    result = await parse_signal_with_ai(signal)
    if result:
        print("AI RESULT:")
        for k, v in sorted(result.items()):
            print(f"  {k}: {v}")
    else:
        print("AI returned None")

asyncio.run(test())
