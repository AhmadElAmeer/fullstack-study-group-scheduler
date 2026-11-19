"""python -m scheduler [--port 8000] [--db scheduler.db]"""

import argparse

from .app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Study group scheduler")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", default="scheduler.db", help="SQLite file (created if missing)")
    args = parser.parse_args()
    create_app(args.db).run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
