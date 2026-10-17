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
        "--mode",
        choices=["theater", "search"],
        default="theater",
        help="Operation mode: 'theater' (single theater) or 'search' (cross-theater search)",
    )
    # 単一劇場モード用
    parser.add_argument(
        "--chain",
        default="aeon",
        help="Cinema chain identifier (default: aeon)",
    )
    parser.add_argument(
        "--theater",
        help="Theater identifier or code (e.g., ebetsu). Required in theater mode.",
    )
    # 横断検索モード用
    parser.add_argument(
        "--title",
        help="Movie title to search across theaters (required in search mode)",
    )
    parser.add_argument(
        "--area",
        help="Area or prefecture to search (e.g., '東京都', '関東'). Required in search mode.",
    )
    # 共通
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
    parser.add_argument(
        "--after",
        help="Filter screenings starting at or after this time (e.g. 'now', 'current', or 'HH:MM'). If 'now' and target date is today, uses local time.",
    )

    args = parser.parse_args(argv)

    try:
        indent = None if args.compact else 2

        if args.mode == "search":
            if not args.title:
                sys.stderr.write(json.dumps({"error": "missing_argument", "message": "--title is required in search mode"}) + "\n")
                return 2
            if not args.area:
                sys.stderr.write(json.dumps({"error": "missing_argument", "message": "--area is required in search mode"}) + "\n")
                return 2

            # after_time の解決 ("now" / "current" の場合は現在時刻 "HH:MM")
            after_time_str = None
            if args.after:
                if args.after.lower() in ("now", "current"):
                    # 対象日付が今日の場合のみ現在時刻を適用
                    if args.date == date.today():
                        after_time_str = datetime.now().strftime("%H:%M")
                else:
                    after_time_str = args.after.strip()

            from .search import search_cross_theater
            resp = search_cross_theater(
                title=args.title,
                area=args.area,
                target_date=args.date,
                after_time=after_time_str,
            )
            print(resp.to_json(indent=indent))
            return 0

        # mode == "theater"
        if not args.theater:
            sys.stderr.write(json.dumps({"error": "missing_argument", "message": "--theater is required in theater mode"}) + "\n")
            return 2

        provider = get_provider(args.chain)
        response = provider.get_schedule_response(args.theater, args.date)
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
