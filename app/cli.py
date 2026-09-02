"""CLI: python -m app.cli discover | match | tailor <job_id>"""
import argparse
import sys

from app.db.session import get_session_factory, init_db


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jobagent")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("discover", help="fetch jobs from all boards in targets.yaml")
    match_p = sub.add_parser("match", help="score jobs against data/resume.md")
    match_p.add_argument("--all", action="store_true", help="rescore already-scored jobs")
    tailor_p = sub.add_parser("tailor", help="tailor resume for a job via Claude")
    tailor_p.add_argument("job_id", type=int)
    args = parser.parse_args(argv)

    init_db()
    db = get_session_factory()()
    try:
        if args.command == "discover":
            from app.discovery.service import run_discovery

            summary = run_discovery(db)
            print(f"created={summary['created']} updated={summary['updated']}")
            for err in summary["errors"]:
                print(f"error: {err}", file=sys.stderr)
            return 1 if summary["errors"] and not (summary["created"] or summary["updated"]) else 0

        if args.command == "match":
            from app.matching.service import run_matching

            result = run_matching(db, rescore_all=args.all)
            print(f"scored {result['scored']} job(s)")
            return 0

        if args.command == "tailor":
            from app.db.models import Job
            from app.tailoring.service import tailor_job

            job = db.get(Job, args.job_id)
            if job is None:
                print(f"job {args.job_id} not found", file=sys.stderr)
                return 1
            record = tailor_job(db, job)
            print(f"tailored resume #{record.id} saved for '{job.title}' @ {job.company}")
            print("--- diff ---")
            print(record.diff)
            return 0
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
