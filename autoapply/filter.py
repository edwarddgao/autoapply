"""Rebuild the candidates table from jobs using filter.sql."""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .db import (
    DB_PATH,
    LOCAL_DB_PATH,
    attached_local,
    get_connection,
    get_local_connection,
    init_db,
    init_local_db,
    load_department_categories,
)

FILTER_PATH = Path(__file__).parent.parent / "filter.sql"
BATCH_SIZE = 20


# ---------------------------------------------------------------------------
# Shared LLM batch classifier
# ---------------------------------------------------------------------------

def _call_claude(prompt: str) -> dict[str, str] | None:
    """Call claude -p --model sonnet, return parsed JSON dict or None."""
    try:
        proc = subprocess.Popen(
            ["claude", "-p", "--model", "sonnet"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        stdout, stderr = proc.communicate(input=prompt, timeout=300)
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        return None
    if proc.returncode != 0:
        return None
    text = stdout.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _classify_parallel(
    batches: list[dict],
    prompt_template: str,
    workers: int = 8,
    label: str = "items",
) -> dict[str, str]:
    """Classify batches in parallel using claude -p. Returns merged mapping."""
    print(f"  {len(batches)} batches, classifying with {workers} workers...")

    mapping: dict[str, str] = {}
    lock = threading.Lock()
    done = [0]

    def process(batch: dict) -> dict[str, str] | None:
        return _call_claude(prompt_template + json.dumps(batch, indent=1))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(process, b): b for b in batches}
        for future in as_completed(futures):
            result = future.result()
            with lock:
                done[0] += 1
                if result:
                    mapping.update(result)
                if done[0] % 25 == 0:
                    print(f"  {done[0]}/{len(batches)} batches done ({len(mapping)} {label})")

    # Sanitize — LLM may return lists instead of strings
    return {k: (v[0] if isinstance(v, list) and v else str(v))
            for k, v in mapping.items()}


# ---------------------------------------------------------------------------
# Department classification
# ---------------------------------------------------------------------------

CLASSIFY_PROMPT = """\
Classify each department into ONE of these categories based on its name AND the sample job titles listed:
- engineering (software engineering, platform, infrastructure, backend, frontend, dev,
  SRE, devops, R&D, hardware, technology)
- data (data science, data engineering, ML, AI, analytics, business intelligence)
- product (product management)
- design (UX, UI, product design, creative, brand design)
- it (information technology, infosec, cybersecurity, IT support, security)
- sales (sales, account executives, business development, revenue, GTM, sales engineering, account management)
- marketing (marketing, growth, content, SEO, user acquisition, comms, PR)
- operations (operations, supply chain, logistics, procurement, manufacturing, quality)
- finance (finance, accounting, tax, audit, treasury)
- people (HR, recruiting, talent, people ops)
- legal (legal, compliance, regulatory, counsel)
- support (customer support, customer service, customer success, customer experience)
- clinical (medical, health, nursing, physician, therapy, veterinary, dental, pharmacy)
- other (junk company names, ambiguous terms, niche non-tech roles)

Classify based on the FUNCTION of the roles, not the company's industry.
"Business Development" and "Sales Engineering" are sales, not engineering.

Return ONLY a JSON object mapping each department string to its category. No markdown fences.

Departments with sample titles:
"""


def classify_new_departments(
    db_path: Path | None = None,
    local_db_path: Path | None = None,
) -> int:
    """Find departments in jobs.db not yet in local.department_categories, classify via claude -p.

    Returns the number of newly classified departments.
    """
    path = db_path or DB_PATH
    local_path = local_db_path or LOCAL_DB_PATH

    # Find unmapped departments and sample titles
    conn = get_connection(path)
    try:
        with attached_local(conn, local_path):
            rows = conn.execute("""
                SELECT DISTINCT j.department
                FROM jobs j
                LEFT JOIN local.department_categories dc ON j.department = dc.department
                WHERE j.department IS NOT NULL AND dc.department IS NULL
                AND j.country IN ('US', 'CA')
            """).fetchall()

        new_depts = [r[0] for r in rows]
        if not new_depts:
            return 0

        print(f"Classifying {len(new_depts)} new departments...")

        # Fetch top 3 titles by frequency for unmapped departments only
        dept_titles: dict[str, list[str]] = {}
        placeholders = ",".join("?" * len(new_depts))
        title_rows = conn.execute(f"""
            SELECT department, title FROM (
                SELECT department, title, COUNT(*) as c,
                       ROW_NUMBER() OVER (PARTITION BY department ORDER BY COUNT(*) DESC) as rn
                FROM jobs
                WHERE department IN ({placeholders})
                GROUP BY department, title
            ) WHERE rn <= 3
        """, new_depts).fetchall()
        for r in title_rows:
            dept_titles.setdefault(r[0], []).append(r[1])
    finally:
        conn.close()

    batches = []
    for i in range(0, len(new_depts), BATCH_SIZE):
        batch = new_depts[i : i + BATCH_SIZE]
        batches.append({d: dept_titles.get(d, []) for d in batch})

    mapping = _classify_parallel(batches, CLASSIFY_PROMPT, label="departments")

    if not mapping:
        return 0

    # Insert into local.db
    local_conn = get_local_connection(local_path)
    try:
        load_department_categories(local_conn, mapping)
    finally:
        local_conn.close()

    print(f"Classified {len(mapping)} new departments")
    return len(mapping)


# ---------------------------------------------------------------------------
# Role classification
# ---------------------------------------------------------------------------

ROLE_PROMPT = """\
Classify each job title into ONE of these software role categories:
- backend (backend, API, server-side, microservices)
- frontend (frontend, UI engineer, web engineer)
- fullstack (full stack, fullstack)
- mobile (iOS, Android, mobile, React Native, Flutter)
- ml (machine learning engineer, ML infrastructure)
- ai (AI engineer, LLM, NLP, computer vision, deep learning, GenAI)
- data-science (data scientist, data analyst, research scientist using data)
- data-eng (data engineer, analytics engineer, ETL, data platform)
- devops (DevOps, SRE, site reliability, cloud engineer, release engineer)
- platform (platform engineer, infrastructure engineer)
- security (security engineer, AppSec, penetration testing)
- qa (QA, SDET, test engineer, automation testing)
- embedded (embedded, firmware, FPGA, ASIC, hardware engineer)
- eng-manager (engineering manager, tech lead, VP engineering)
- tpm (technical program manager, technical project manager)
- product-mgr (product manager, product owner)
- design (product designer, UX/UI designer, UX researcher)
- swe (generic "software engineer" or "engineer" with no clear specialization)
- non-software (mechanical, electrical, civil, chemical, manufacturing, \
construction, clinical, driver, technician — not software roles)
- other (cannot determine)

Classify based on the role's FUNCTION, not the company or department.
A "Software Engineer" with no specialization keywords is "swe".
"Solutions Architect" and "Forward Deployed Engineer" are "swe".
"Technical Program Manager" is "tpm", not "eng-manager".

Return ONLY a JSON object mapping each title to its role. No markdown fences.

Titles:
"""

# Keywords that can classify a title without LLM.
# Order matters — first match wins. More specific rules come first.
_ROLE_KEYWORD_RULES: list[tuple[str, list[str]]] = [
    ("non-software", [
        r"\b(mechanical|electrical|civil|structural|chemical|surveyor|welder|"
        r"electrician|plumber|hvac|piping|manufacturing eng|maintenance eng|"
        r"assembly|machinist|construction|driver|foreman|"
        r"psycholog|nurse|veterinar|dental|therapist|physician|"
        r"cdl|technologist|mammograph|warehouse|autonomous vehicle|"
        r"cad designer|rater|building engineer|controls engineer|"
        r"field service|field technician|network engineer|"
        r"project engineer|process engineer|power electronics|"
        r"thermal engineer|design engineer|manufacturing|"
        r"test engineer(?!.*(software|automation)))\b",
    ]),
    ("tpm", [
        r"\btechnical program manager",
        r"\btechnical project manager",
        r"\bprogram manager",
        r"\bscrum master",
    ]),
    ("product-mgr", [
        r"\bproduct manager", r"\bproduct owner",
    ]),
    ("design", [
        r"\bproduct designer", r"\bux.{0,3}ui",
        r"\bux designer", r"\bui designer",
        r"\bux research", r"\binteraction designer",
    ]),
    ("eng-manager", [
        r"\b(engineering manager|eng manager|vp.?engineer|"
        r"director.?engineer|director of engineer|head of engineer|"
        r"manager.{0,5}software|manager.{0,5}engineer)\b",
        r"^of engineering$",  # "Director of Engineering" after normalization
        r"^engineering$",  # "Head of Engineering" after normalization
    ]),
    ("ml", [r"\b(machine learning|ml engineer|ml infra|ml ops|mlops)\b",
            r"\bai/ml\b", r"\bml/ai\b"]),
    ("ai", [
        r"\b(ai engineer|artificial intelligence|llm|nlp|computer vision|"
        r"deep learning|genai|generative ai|ai platform|ai infra|"
        r"ai research|ai data)\b",
    ]),
    ("data-science", [r"\bdata scien", r"\bdata analyst",
                      r"\bresearch scientist", r"\bquantitative research",
                      r"\bbusiness intelligence\b", r"\bbi analyst"]),
    ("data-eng", [r"\bdata engineer", r"\banalytics engineer", r"\betl\b",
                  r"\bdata platform", r"\bdata architect",
                  r"\bdatabase engineer", r"\bdatabase reliab"]),
    ("frontend", [r"\b(frontend|front-end|front end)\b"]),
    ("backend", [r"\b(backend|back-end|back end)\b"]),
    ("fullstack", [r"\b(full[\s-]*stack|fullstack)\b"]),
    ("mobile", [r"\b(ios|android|mobile|react native|flutter)\b.*engineer",
                r"\b(ios|android|mobile) (developer|eng)"]),
    ("devops", [r"\b(devops|dev ?ops|devsecops|site reliab|"
                r"reliability engineer|sre)\b",
                r"\b(cloud engineer|release engineer|build engineer)"]),
    ("security", [r"\b(security engineer|appsec|infosec|penetration|"
                  r"security analyst|cybersecurity)\b"]),
    ("qa", [r"\b(qa|quality assurance|sdet|"
            r"automation engineer)\b"]),
    ("platform", [r"\b(platform engineer|infrastructure engineer|"
                  r"systems? engineer)\b"]),
    ("embedded", [r"\b(embedded|firmware|fpga|asic|hardware engineer|"
                  r"robotics engineer)\b"]),
    ("swe", [r"\b(software engineer|software developer|software dev\b|"
             r"application developer|web developer|"
             r"solutions architect|solutions engineer|"
             r"forward deployed|product engineer|founding engineer|"
             r"\.net|java developer|python developer|python engineer|"
             r"ruby developer|golang|rust developer|"
             r"c\+\+|node\.?js developer|typescript|react developer|"
             r"servicenow developer|member of technical)\b",
             r"^engineer$", r"^developer$",
             r"^software eng",
             ]),
]


def normalize_title(title: str) -> str:
    """Normalize a job title for role classification lookup."""
    t = title.lower().strip()
    # Remove seniority prefixes
    t = re.sub(
        r"\b(senior|sr\.?|staff|principal|lead|junior|jr\.?|"
        r"entry[- ]level|associate|distinguished)\b",
        "", t,
    )
    # Remove levels
    t = re.sub(r"\b(i{1,3}|iv|v|vi|[1-6])\b", "", t)
    # Remove location/remote suffixes
    t = re.sub(
        r"\s*[-–—]\s*(remote|hybrid|onsite|.*"
        r"(latin america|emea|apac|usa|us|uk|canada|india|europe)).*$",
        "", t, flags=re.I,
    )
    # Remove parentheticals
    t = re.sub(r"\s*\(.*?\)\s*", " ", t)
    # Collapse whitespace
    t = re.sub(r"\s+", " ", t).strip(" ,-–")
    return t


def _keyword_classify_role(title: str) -> str | None:
    """Try to classify a title by keywords. Returns role or None."""
    t = title.lower()
    for role, patterns in _ROLE_KEYWORD_RULES:
        for p in patterns:
            if re.search(p, t):
                return role
    return None


def classify_new_roles(
    db_path: Path | None = None,
    local_db_path: Path | None = None,
) -> int:
    """Classify unmapped titles in engineering/data departments into roles.

    Returns the number of newly classified titles.
    """
    path = db_path or DB_PATH
    local_path = local_db_path or LOCAL_DB_PATH

    conn = get_connection(path)
    try:
        with attached_local(conn, local_path):
            # Get all titles from engineering/data departments
            rows = conn.execute("""
                SELECT DISTINCT j.title
                FROM jobs j
                JOIN local.department_categories dc ON j.department = dc.department
                WHERE dc.category IN ('engineering', 'data')
                AND j.country IN ('US', 'CA')
            """).fetchall()

            # Fetch already-mapped normalized titles
            existing = {
                r[0]
                for r in conn.execute(
                    "SELECT normalized_title FROM local.role_categories"
                ).fetchall()
            }

        all_titles = [r[0] for r in rows]

        # Normalize, deduplicate, and filter out already-mapped
        norm_to_raw: dict[str, str] = {}
        for t in all_titles:
            n = normalize_title(t)
            if n and n not in norm_to_raw and n not in existing:
                norm_to_raw[n] = t

        unmapped = norm_to_raw
        if not unmapped:
            return 0

        print(f"Classifying {len(unmapped)} new role titles...")

        # Pass 1: keyword classification
        keyword_mapped: dict[str, str] = {}
        need_llm: dict[str, str] = {}
        for norm, raw in unmapped.items():
            role = _keyword_classify_role(norm)
            if role:
                keyword_mapped[norm] = role
            else:
                need_llm[norm] = raw

        print(f"  Keywords: {len(keyword_mapped)}, LLM needed: {len(need_llm)}")

    finally:
        conn.close()

    # Pass 2: LLM classification for remainder
    llm_mapped: dict[str, str] = {}
    if need_llm:
        titles_list = list(need_llm.keys())
        batches = []
        for i in range(0, len(titles_list), BATCH_SIZE):
            batch = titles_list[i : i + BATCH_SIZE]
            batches.append({t: [] for t in batch})

        llm_mapped = _classify_parallel(
            batches, ROLE_PROMPT, label="roles",
        )

    all_mapped = {**keyword_mapped, **llm_mapped}
    if not all_mapped:
        return 0

    local_conn = get_local_connection(local_path)
    try:
        local_conn.executemany(
            "INSERT OR REPLACE INTO role_categories (normalized_title, role) "
            "VALUES (?, ?)",
            all_mapped.items(),
        )
        local_conn.commit()
    finally:
        local_conn.close()

    print(f"Classified {len(all_mapped)} new roles "
          f"({len(keyword_mapped)} keyword, {len(llm_mapped)} LLM)")
    return len(all_mapped)


SELECT_COLS = """
    j.job_id, j.ats, j.title, j.company_name, j.description_text,
    j.location_raw, j.city, j.state, j.country, j.is_remote,
    j.department, dc.category AS department_category,
    rc.role AS role_category,
    j.employment_type, j.experience_level,
    j.min_salary, j.max_salary, j.apply_url, j.first_seen_at
"""


def rebuild_candidates(
    db_path: Path | None = None,
    filter_path: Path | None = None,
    local_db_path: Path | None = None,
) -> int:
    """Rebuild the candidates table using the WHERE clause from filter.sql.

    Returns the number of candidates.
    """
    fp = filter_path or FILTER_PATH
    if not fp.exists():
        raise FileNotFoundError(f"{fp} not found. Copy filter.example.sql and edit it.")

    where = fp.read_text().strip()
    if not where:
        raise ValueError("filter.sql is empty.")

    path = db_path or DB_PATH
    init_db(path)
    init_local_db(local_db_path)

    # Classify any new departments and roles before rebuilding
    classify_new_departments(db_path=path, local_db_path=local_db_path)
    classify_new_roles(db_path=path, local_db_path=local_db_path)

    conn = get_connection(path)
    try:
        # Build a normalized_title → role lookup for the JOIN.
        # We register normalize_title as a SQLite function so the JOIN
        # can match raw titles to their normalized form.
        conn.create_function("normalize_title", 1, normalize_title)

        with attached_local(conn, local_db_path):
            conn.execute("DROP TABLE IF EXISTS candidates_new")
            conn.execute(f"""
                CREATE TABLE candidates_new AS
                SELECT {SELECT_COLS}
                FROM jobs j
                LEFT JOIN local.department_categories dc ON j.department = dc.department
                LEFT JOIN local.role_categories rc
                    ON normalize_title(j.title) = rc.normalized_title
                LEFT JOIN local.applications a ON j.job_id = a.job_id
                LEFT JOIN local.exclusions e ON j.job_id = e.job_id
                WHERE a.job_id IS NULL AND e.job_id IS NULL
                AND ({where})
            """)
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_candidates_new_jid ON candidates_new(job_id)"
            )

            count = conn.execute("SELECT COUNT(*) FROM candidates_new").fetchone()[0]
            conn.execute("DROP TABLE IF EXISTS candidates")
            conn.execute("ALTER TABLE candidates_new RENAME TO candidates")
            conn.commit()
    finally:
        conn.close()

    print(f"Rebuilt candidates table: {count} rows")
    return count


_RECLASSIFY_TARGETS = {
    "departments": ("department_categories", classify_new_departments),
    "roles": ("role_categories", classify_new_roles),
}


def reclassify_all(
    target: str,
    db_path: Path | None = None,
    local_db_path: Path | None = None,
) -> int:
    """Drop all mappings for *target* and reclassify from scratch."""
    table, classify_fn = _RECLASSIFY_TARGETS[target]
    local_path = local_db_path or LOCAL_DB_PATH
    local_conn = get_local_connection(local_path)
    try:
        local_conn.execute(f"DELETE FROM {table}")  # noqa: S608 — table is from trusted dict
        local_conn.commit()
    finally:
        local_conn.close()

    print(f"Cleared all {target} mappings. Reclassifying...")
    return classify_fn(db_path=db_path, local_db_path=local_db_path)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Rebuild candidates table from filter.sql")
    parser.add_argument("--db", type=Path, default=None, help="Path to jobs.db")
    parser.add_argument("--filter", type=Path, default=None, help="Path to filter.sql")
    parser.add_argument("--reclassify", action="store_true",
                        help="Drop all department mappings and reclassify from scratch")
    parser.add_argument("--reclassify-roles", action="store_true",
                        help="Drop all role mappings and reclassify from scratch")
    args = parser.parse_args()

    try:
        if args.reclassify:
            reclassify_all("departments", db_path=args.db)
        elif args.reclassify_roles:
            reclassify_all("roles", db_path=args.db)
        else:
            rebuild_candidates(db_path=args.db, filter_path=args.filter)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
