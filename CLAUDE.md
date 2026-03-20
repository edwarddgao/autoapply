# autoapply

Automated job application pipeline. Downloads `jobs.db` from the jobsdb repo, filters candidates, then spawns `claude -p` agents to fill application forms via Chrome MCP.

## Architecture

```
Local machine
┌──────────────────────────┐
│ update.py  ← jobs.db     │
│ filter.py  → candidates  │
│ pipeline.py              │
│   └─ claude -p per job   │
│      └─ Chrome MCP       │
│ search.py ←→ local.db    │
└──────────────────────────┘
```

## Running

```bash
env -u CLAUDECODE python -m autoapply.pipeline                  # 4 concurrent (default)
env -u CLAUDECODE python -m autoapply.pipeline --concurrency 1
```

If run from inside Claude Code, prefix with `env -u CLAUDECODE`.

## Files

### Package (`autoapply/`)
- `pipeline.py` — orchestrator: creates tabs, spawns agents, marks results
- `search.py` — `find_candidates()`, `mark_applied()`, `mark_excluded()`, `delete_job()`
- `filter.py` — rebuilds `candidates` table from `filter.sql` WHERE clause
- `db.py` — schema, connections, helpers. Two databases: `jobs.db` (scraped) + `local.db` (applications/exclusions)
- `update.py` — downloads `jobs.db` from GitHub Releases
- `gmail.py` — Gmail IMAP helper for Greenhouse verification codes

### Root
- `jobs.db` — scraped job data (~250k jobs). Safe to overwrite on update.
- `local.db` — applications + exclusions. Never overwrite.
- `filter.sql` — SQL WHERE clause for candidate filtering
- `agent_prompt.txt` — system prompt for pipeline agents (resume, workflow, known gaps)
- `logs/` — per-job stream-json logs (`{job_id}.jsonl`) + `pipeline.log`

## Databases

### `jobs.db` (replaceable, downloaded from jobsdb repo)
- `companies` — slugs and metadata
- `jobs` — all scraped jobs
- `candidates` — materialized filtered view (rebuilt by `filter.py`)
- `meta` — key-value store

### `local.db` (persistent, never overwrite)
- `applications` — submitted jobs
- `exclusions` — permanently excluded jobs (3+ failures)

### Candidate filtering
Edit `filter.sql` then run `python -m autoapply.filter` to rebuild. The WHERE clause filters directly on job title keywords, location, seniority, etc. Excludes jobs already in `local.db` applications/exclusions.

## Tracking

- **SUBMITTED** → `mark_applied(job_id)` in `local.db`
- **FAILED** → retried in next pipeline run (not recorded)
- **3+ failures** → `mark_excluded(job_id, reason)` — permanently excluded

## Pipeline Details

### Error handling
- 3+ errors within 60s → stop (Chrome likely crashed), attempt Chrome restart
- Per-job timeout: 600s
- DB is the only state — restart script to resume

### Agent prompt
```
Navigate tab {TAB_ID} to {URL}. Company: {NAME} | Role: {TITLE}
```

## Skill Maintenance

After reviewing agent logs in `logs/`, update `agent_prompt.txt`:
1. Add cross-platform observations to Known Simplify Gaps
2. Remove outdated gaps
3. Update Known Answers with new Q&A pairs
4. Do NOT add company-specific form quirks
