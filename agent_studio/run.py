#!/usr/bin/env python3
"""
Agent Studio — Run the standalone development dashboard.

Usage:
    python -m agent_studio.run
    python agent_studio/run.py
    python agent_studio/run.py --port 5100
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_studio.app import create_app


def main():
    parser = argparse.ArgumentParser(description="Agent Studio - AI Development Dashboard")
    parser.add_argument("--port", type=int, default=int(os.environ.get("AGENT_STUDIO_PORT", 5100)),
                        help="Port to run on (default: 5100)")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Host to bind to (default: 127.0.0.1)")
    parser.add_argument("--debug", action="store_true",
                        help="Enable debug mode")
    args = parser.parse_args()

    app = create_app()

    print(f"")
    print(f"  Agent Studio for BotifyTrades")
    print(f"  ==============================")
    print(f"  Dashboard:  http://{args.host}:{args.port}")
    print(f"  Repo root:  {os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}")
    print(f"")

    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    main()
