---
name: setup
description: Interactive setup wizard — verifies prerequisites, generates agent_prompt.txt and filter.sql, runs first DB download.
user-invocable: true
arguments: ""
---

# Setup Wizard

Guides the user through first-time setup of autoapply.

## Steps

### 1. Verify prerequisites

Check each and report status. If any fail, explain how to fix before continuing.

Detect the platform first (`uname` or check for common paths). Use `python3` on macOS/Linux, `python` on Windows.

```bash
# Python 3.11+
python3 --version        # macOS/Linux
python --version          # Windows

# Required packages (httpx is a real dependency)
python3 -c "import httpx; from autoapply import db; print('ok')"   # macOS/Linux
python -c "import httpx; from autoapply import db; print('ok')"     # Windows

# Claude CLI
claude --version

# Google Chrome installed
# macOS:
ls "/Applications/Google Chrome.app" 2>/dev/null
# Linux:
which google-chrome 2>/dev/null || which chromium-browser 2>/dev/null
# Windows (PowerShell):
Test-Path "C:\Program Files\Google\Chrome\Application\chrome.exe"
```

If the autoapply package import fails, they may need to install it:
```bash
pip install -e .
```

### 2. Verify Chrome MCP

Check if Claude CLI has Chrome MCP configured:

```bash
claude mcp list 2>/dev/null
```

If Chrome MCP is not listed, tell the user:
- Install the [Claude in Chrome](https://chromewebstore.google.com/detail/claude-in-chrome/odciglefcoihjkbienpomfadjckmcamgp) extension
- Then run: `claude mcp add --transport chrome chrome`
- Link: https://docs.anthropic.com/en/docs/claude-code/chrome-mcp

### 3. Verify Simplify extension

Open Chrome and check if Simplify is installed:

- Call `tabs_context_mcp` with `createIfEmpty=true`
- Call `navigate` to `https://simplify.jobs`
- Take a screenshot — look for the Simplify "S" icon in the toolbar

If not visible, tell the user:
- Install from https://simplify.jobs
- Create a Simplify account and fill out their profile (name, education, experience)
- Upload their resume PDF to Simplify
- This is critical — Simplify handles autofill and resume uploads

### 4. Generate agent_prompt.txt

Read `agent_prompt.example.txt` as the template. Use AskUserQuestion to collect the user's information step by step. Do NOT generate answers — every value must come from the user.

#### Step 4a: Resume

Ask the user to provide their resume. Accept either:
- A file path (PDF or tex) — read it and extract the text
- Pasted text

From the resume, extract: name, contact info, education, experience, projects, skills. Show the user what you extracted and confirm it's correct.

#### Step 4b: Known Answers

Ask each question individually via AskUserQuestion. These are the most common questions on job application forms — the agent needs correct answers for all of them.

**Work authorization:**
- "Are you legally authorized to work in the US?" (Yes/No)
- "Will you now or in the future require sponsorship for the US?" (Yes/No)
- If yes to sponsorship: what visa type?
- "Are you legally authorized to work in Canada?" (Yes/No)
- "Will you now or in the future require sponsorship for Canada?" (Yes/No)

**Education:**
- GPA (or N/A if they don't want to share)
- Graduation date (month and year)
- Degree type and major

**Employment:**
- Current company (or N/A if unemployed)
- Years of experience (0-1, 1-3, 3-5, 5+)
- Previously worked at any notable companies? (for "have you worked here before" questions)

**Availability:**
- Earliest start date
- Willing to relocate? (Yes/No)
- Willing to work in-person/hybrid? (Yes/No)

**Personal:**
- Pronouns
- GitHub username (if applicable)
- LinkedIn URL (if applicable)
- Personal website/portfolio (if applicable)
- Preferred programming language
- Top 3 programming languages

**Compliance:**
- Security clearance? (Yes/No/Not eligible)
- Non-compete agreement? (Yes/No, length in months)
- SMS/text consent for recruiting? (Yes/No)
- BrightHire/background check consent? (Yes/No)

**Preferences:**
- Salary expectations strategy (recommend: "enter 0 or N/A — never give a real number")
- "How did you hear about us?" default answer

#### Step 4c: Essay response

Ask: "What should the agent write for open-ended/essay questions? This gets pasted into every required essay field. Keep it short — 1-2 sentences."

Suggest a generic example but let the user write their own.

#### Step 4d: Generate and confirm

Use all collected answers to generate `agent_prompt.txt` based on the template. Also update:
- GitHub username references in the Simplify gaps section
- Simplify gap corrections to match their specific answers (e.g., work auth values, security clearance)
- Degree in Greenhouse degree multi-select gap

Write the file, then **open it for the user** and ask them to confirm everything is accurate before proceeding. This file controls everything the agent says on their behalf — a wrong answer could misrepresent them to employers.

### 5. Customize filter.sql

If `filter.sql` doesn't exist, create it from a sensible default. Then ask the user:

- What **countries** are you targeting? (show current: US, CA)
- What **job title keywords** should match? (show current list: engineer, developer, scientist, architect, researcher, etc.)
- Any **seniority keywords to exclude**? (show current list — senior, staff, principal, director, etc.)
- Any **non-software title keywords to exclude**? (show current list — mechanical, electrical, etc. Ask if they want to add/remove)
- Any **companies to exclude**? (show current list, explain why — e.g., citizenship requirements like SpaceX)

Write the updated `filter.sql`. Then rebuild candidates:

```bash
python3 -m autoapply.filter   # macOS/Linux
python -m autoapply.filter     # Windows
```

Report how many candidates match.

### 6. Configure Gmail for Greenhouse verification (optional)

Some Greenhouse applications require an email verification code. The pipeline can fetch these automatically via IMAP if configured.

Ask if the user wants to set this up. If yes:

1. They need a Gmail account and a [Google App Password](https://myaccount.google.com/apppasswords) (requires 2FA enabled)
2. Create a `.env` file in the project root with:
   ```
   GMAIL_EMAIL=you@gmail.com
   GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
   ```
3. The agent calls `python -m autoapply.gmail "COMPANY"` at runtime to fetch codes

If they skip this, Greenhouse jobs requiring email verification will fail and be excluded automatically. They can set it up later.

### 7. Set up jobs database

autoapply gets its job data from `jobs.db`, which is downloaded from a GitHub repo's Releases as `jobs.db.gz`. By default, `update.py` points at `edwarddgao/jobsdb`. Ask the user how they want to source job data:

**Option A: Use the jobsdb scraper (recommended)**
The user needs their own copy of the [jobsdb](https://github.com/edwarddgao/jobsdb) repo, which scrapes Lever, Greenhouse, and Ashby ATS APIs and publishes `jobs.db.gz` as a GitHub Release artifact. Steps:
1. Fork or clone `edwarddgao/jobsdb`
2. Set up the GitHub Actions workflow (needs `SIMPLIFY_TYPESENSE_API_KEY` secret for discovery) or run locally:
   ```bash
   python -m jobsdb.discover --source all
   python -m jobsdb.scrape --db jobs.db
   ```
3. Create a GitHub Release with `jobs.db.gz` as an asset (the CI workflow does this automatically)
4. Download using their repo:
```bash
python3 -m autoapply.update --repo owner/repo   # macOS/Linux
python -m autoapply.update --repo owner/repo     # Windows
```
   Or update `GITHUB_REPO` in `autoapply/update.py` to change the default.

**Option B: Provide jobs.db directly**
If the user already has a `jobs.db` file (from any source), they can place it in the project root. It must have `companies` and `jobs` tables matching the jobsdb schema.

After the database is in place, rebuild candidates with their filters:

```bash
python3 -m autoapply.filter   # macOS/Linux
python -m autoapply.filter     # Windows
```

Report:
- Total jobs in database
- Candidates matching their filters
- Ready to run pipeline

### 8. Summary

Print a summary:
- Prerequisites: all verified
- `agent_prompt.txt`: generated with their info
- `filter.sql`: customized
- Database: downloaded and filtered (if they chose to download)
- Next step to start applying (remind about unsetting `CLAUDECODE` if running from Claude Code):
  - macOS/Linux: `env -u CLAUDECODE python -m autoapply.pipeline`
  - Windows (PowerShell): `$env:CLAUDECODE=$null; python -m autoapply.pipeline`
