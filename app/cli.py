"""CLI: python -m app.cli discover | match | tailor <job_id>"""
import argparse
import sys

from app.db.session import get_session_factory, init_db


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jobagent")
    sub = parser.add_subparsers(dest="command", required=True)
    disc = sub.add_parser("discover", help="fetch jobs from every company board + enabled aggregators")
    disc.add_argument("--batch", type=int, default=25, help="companies per slice")
    comp = sub.add_parser("companies", help="manage the company registry")
    comp_sub = comp.add_subparsers(dest="companies_cmd", required=True)
    comp_sub.add_parser("seed", help="load config/vertical/<v>/companies.yaml into the DB")
    comp_sub.add_parser("list", help="list companies with fetch status and open-job counts")
    add = comp_sub.add_parser("add", help="add a company from its careers URL (auto-detects the ATS)")
    add.add_argument("careers_url")
    add.add_argument("--name")
    add.add_argument("--tier", type=int, choices=[1, 2, 3])
    ver = comp_sub.add_parser("verify", help="fetch every board once and report not_found/error boards")
    ver.add_argument("--only-unverified", action="store_true")
    match_p = sub.add_parser("match", help="score jobs against data/resume.md")
    match_p.add_argument("--all", action="store_true", help="rescore already-scored jobs")
    tailor_p = sub.add_parser("tailor", help="tailor resume for a job via Claude")
    tailor_p.add_argument("job_id", type=int)
    args = parser.parse_args(argv)

    init_db()
    db = get_session_factory()()
    from app.auth import ensure_owner
    from app.db.tenancy import as_user

    owner = ensure_owner(db)
    with as_user(owner.id):
        return _run(args, db, owner.id)


def _run(args, db, user_id: int) -> int:
    try:
        if args.command == "discover":
            from app.ingest.seed import seed_companies
            from app.ingest.service import run_discovery, run_summary

            seeded = seed_companies(db)
            print(f"companies seeded: +{seeded['created']} (updated {seeded['updated']})")
            run = run_discovery(db, user_id=user_id, time_budget_seconds=10**9, batch_size=args.batch)
            s = run_summary(run)
            print(f"run #{s['id']} {s['status']}: companies {s['processed_companies']}/{s['total_companies']}, "
                  f"created={s['created']} updated={s['updated']} closed={s['closed']} duplicates={s['duplicates']}")
            for e in s["sources"]:
                flag = "" if e["status"] == "ok" else f"  <- {e['status']} {e.get('error', '')}"
                print(f"  {e['source']:16} {e['target']:40} {e['count']:5} jobs {e['seconds']:6.1f}s{flag}")
            return 0

        if args.command == "companies":
            return _companies(args, db)

        if args.command == "match":
            from app.matching.service import run_matching

            result = run_matching(db, rescore_all=args.all, user_id=user_id)
            print(f"scored {result['scored']} job(s) against {result['resume_source']}")
            return 0

        if args.command == "tailor":
            from app.db.models import Job
            from app.tailoring.service import tailor_job

            job = db.get(Job, args.job_id)
            if job is None:
                print(f"job {args.job_id} not found", file=sys.stderr)
                return 1
            record = tailor_job(db, job, user_id=user_id)
            print(f"tailored resume #{record.id} saved for '{job.title}' @ {job.company}")
            print("--- diff ---")
            print(record.diff)
            return 0
    finally:
        db.close()
    return 0


def _companies(args, db) -> int:
    from sqlalchemy import func, select

    from app.db.models import Company, Job
    from app.ingest.seed import seed_companies

    if args.companies_cmd == "seed":
        r = seed_companies(db)
        print(f"created={r['created']} updated={r['updated']}")
        return 0
    if args.companies_cmd == "list":
        counts = dict(db.execute(select(Job.company_id, func.count(Job.id)).where(Job.status == "open")
                                 .group_by(Job.company_id)).all())
        rows = db.scalars(select(Company).order_by(Company.tier_seed, Company.name)).all()
        print(f"{'id':>4} T {'name':32} {'ats':15} {'status':10} {'open':>5}  slug")
        for c in rows:
            print(f"{c.id:>4} {c.tier_override or c.tier or c.tier_seed or '-'} {c.name[:32]:32} "
                  f"{c.ats_provider or '-':15} {c.last_fetch_status:10} {counts.get(c.id, 0):>5}  {c.ats_slug}")
        return 0
    if args.companies_cmd == "add":
        from app.ingest.seed import slugify
        from app.sources.detect import detect

        hit = detect(args.careers_url)
        if hit is None:
            print("could not detect a supported ATS from that URL", file=sys.stderr)
            return 1
        provider, ats_slug = hit
        name = args.name or ats_slug.split("/")[0].split(".")[0].replace("-", " ").title()
        company = db.scalar(select(Company).where(Company.slug == slugify(name)))
        if company is None:
            company = Company(name=name, slug=slugify(name), headcount_band="<500")
            db.add(company)
        company.ats_provider, company.ats_slug, company.careers_url = provider, ats_slug, args.careers_url
        company.tier_seed = args.tier or company.tier_seed or 3
        db.commit()
        print(f"added/updated {company.name}: {provider}/{ats_slug} (tier {company.tier_seed})")
        return 0
    if args.companies_cmd == "verify":
        from app.ingest.service import ingest_company

        q = select(Company).where(Company.active.is_(True), Company.ats_provider.isnot(None))
        if args.only_unverified:
            q = q.where(Company.verified.is_(False))
        bad = 0
        for c in db.scalars(q.order_by(Company.name)).all():
            e = ingest_company(db, c, user_id=_owner_id(db))
            mark = "ok " if e["status"] == "ok" else "BAD"
            bad += e["status"] != "ok"
            print(f"{mark} {c.name[:32]:32} {c.ats_provider:15} {c.ats_slug:45} {e['count']:5} {e['error']}")
        print(f"{bad} board(s) need fixing -> `python -m app.cli companies add <careers-url>`")
        return 0
    return 1


def _owner_id(db) -> int:
    from app.auth import ensure_owner

    return ensure_owner(db).id


if __name__ == "__main__":
    raise SystemExit(main())
