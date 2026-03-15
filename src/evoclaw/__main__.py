import argparse
import asyncio
import os
import signal
import sys

from evoclaw.config import load_config
from evoclaw.daemon import Daemon
from evoclaw.log import format_god_log
from evoclaw.world import init_world


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="evoclaw", description="EvoClaw digital life form"
    )
    sub = parser.add_subparsers(dest="command")
    _ = sub.add_parser("start", help="Start the daemon")
    _ = sub.add_parser("init-world", help="Initialize the world directory")
    _ = sub.add_parser("stop", help="Stop the running daemon")

    fmt_parser = sub.add_parser("format-log", help="Pretty-print god.jsonl")
    _ = fmt_parser.add_argument(
        "--no-color", action="store_true", help="Disable ANSI colors"
    )
    _ = fmt_parser.add_argument(
        "--generation", "-g", type=int, default=None, help="Show only this generation"
    )
    _ = fmt_parser.add_argument(
        "log_file",
        nargs="?",
        default=None,
        help="Path to god.jsonl (default: logs/god.jsonl)",
    )

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
    elif command == "format-log":
        log_file: str = args.log_file or os.path.join("logs", "god.jsonl")
        if not os.path.isfile(log_file):
            print(f"Log file not found: {log_file}", file=sys.stderr)
            sys.exit(1)
        format_god_log(
            log_file,
            color=not args.no_color,
            generation=args.generation,
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
