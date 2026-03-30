# SecDevOps Crews

AI-powered security code review that scans open PRs and posts findings as GitHub comments.

## How It Works

```
Open PRs on GitHub → before_kickoff fetches diffs → LLM analyzes for vulnerabilities → Posts findings as PR comments
```

1. **before_kickoff** (Python): fetches all open PRs from carespace-ai org via `gh` CLI, gets diffs and changed files
2. **LLM** (security reviewer): analyzes each diff for OWASP Top 10 vulnerabilities, hardcoded secrets, missing validation
3. **LLM** (post findings): formats findings as markdown and posts as PR comments via `gh pr comment`

## Architecture

```
secdevops-crews/
├── pyproject.toml
├── src/
│   ├── main.py                    # SecDevOpsFlow dispatcher
│   ├── crews/
│   │   └── pr_security/           # PR security scanning crew
│   │       ├── crew.py            # before_kickoff + agents + tasks
│   │       └── config/
│   │           ├── agents.yaml    # Security reviewer agent
│   │           └── tasks.yaml     # Review + post tasks
│   └── shared/
│       ├── tools/
│       │   └── github_pr.py       # gh CLI tools (list PRs, get diff, post comment)
│       └── skills/                # Security knowledge base
│           ├── code-standards-base/
│           ├── security-auditor/
│           └── code-review-orchestrator/
└── .env
```

## Skills (Knowledge Base)

From [agente-skill-oop](https://github.com/gugastork/agente-skill-oop):

| Skill | Type | Purpose |
|-------|------|---------|
| code-standards-base | Abstract | OWASP Top 10, SOLID principles, performance rules |
| security-auditor | Specialist | Vulnerability detection, severity classification |
| code-review-orchestrator | Orchestrator | Coordinates security + performance review |

## What It Catches

- **OWASP Top 10**: SQL injection, XSS, CSRF, broken auth, security misconfig, sensitive data exposure, broken access control, insecure deserialization, insufficient logging
- **Hardcoded secrets**: API keys, passwords, tokens in source code
- **Missing validation**: unvalidated user input, missing sanitization
- **Unsafe patterns**: eval(), exec(), unsafe deserialization, debug mode in production

## PR Comment Format

```markdown
## 🔒 Security Review

**PR:** carespace-ui#176 — feat: migrate PDF reports
**Reviewer:** SecDevOps AI

### Findings

#### 🔴 Critical: Hardcoded API Key
**File:** `src/config/api.ts:12`
**Issue:** AWS access key hardcoded in source file.
**Fix:** Move to environment variable: `process.env.AWS_ACCESS_KEY`

---
*Automated security review by SecDevOps AI*
```

## Setup

### Prerequisites

- `gh` CLI installed and authenticated (`gh auth login`)
- Access to carespace-ai GitHub org

### Required Secrets

| Secret | Used by |
|--------|---------|
| `OPENAI_API_KEY` | LLM for security analysis |

### Run

```bash
cd src
python main.py
```

Or via CrewHub with `crew_name=pr_security`.
