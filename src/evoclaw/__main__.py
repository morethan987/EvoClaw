import argparse
import asyncio
import os
import signal
import sys

from evoclaw.config import load_config
from evoclaw.daemon import Daemon
from evoclaw.world import init_world


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="evoclaw", description="EvoClaw digital life form"
    )
    sub = parser.add_subparsers(dest="command")
    _ = sub.add_parser("start", help="Start the daemon")
    _ = sub.add_parser("init-world", help="Initialize the world directory")
    _ = sub.add_parser("stop", help="Stop the running daemon")
    args = parser.parse_args()
    command = getattr(args, "command", None)

    if command == "start":
        config = load_config()
        daemon = Daemon(config)
        asyncio.run(daemon.run())
    elif command == "init-world":
        config = load_config()
        init_world(config)
        print("World initialized.")
    elif command == "stop":
        config = load_config()
        pid_path = os.path.join(config.world_dir, "evoclaw.pid")
        try:
            with open(pid_path, encoding="utf-8") as f:
                pid = int(f.read().strip())
            os.kill(pid, signal.SIGTERM)
            print(f"Sent SIGTERM to {pid}")
        except FileNotFoundError:
            print("No PID file found — daemon not running?", file=sys.stderr)
            sys.exit(1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
