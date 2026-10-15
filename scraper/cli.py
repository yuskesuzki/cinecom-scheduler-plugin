import argparse
import json
import sys
from datetime import date, datetime
from .providers import get_provider
from .sanitizer import UnsafeUrlError


def parse_date(date_str: str) -> date:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError as e:
        raise argparse.ArgumentTypeError(
            f"Invalid date format (expected YYYY-MM-DD): {date_str}"
        ) from e


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Fetch unified cinema schedule JSON.")
    parser.add_argument(
        "--chain",
        default="aeon",
        help="Cinema chain identifier (default: aeon)",
    )
    parser.add_argument(
        "--theater",
        required=True,
        help="Theater identifier or code (e.g., ebetsu)",
    )
    parser.add_argument(
        "--date",
        type=parse_date,
        default=date.today(),
        help="Target date in YYYY-MM-DD format (default: today)",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Output compact single-line JSON for QML parsing",
    )

    args = parser.parse_args(argv)

    try:
        provider = get_provider(args.chain)
        response = provider.get_schedule_response(args.theater, args.date)
        indent = None if args.compact else 2
        print(response.to_json(indent=indent))
        return 0

    except UnsafeUrlError as e:
        sys.stderr.write(
            json.dumps({"error": "security_violation", "message": str(e)}) + "\n"
        )
        return 2
    except Exception as e:
        sys.stderr.write(
            json.dumps({"error": "fetch_failed", "message": str(e)}) + "\n"
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
