---
name: carespace-code-review
version: 2.0.0
type: orchestrator
description: Coordinates security audit + code quality review for CareSpace PRs.
tags: [orchestrator, code-review, security, carespace]
---

# CareSpace Code Review Orchestrator

## PURPOSE

Coordinate full PR review for CareSpace AI. Each PR gets a security audit (HIPAA + OWASP) and code quality check, posted as a single PR comment.

## WORKFLOW

```
PR Diff → Classify Files → Security Audit → Code Quality → Unified Comment
```

### Phase 1: Classify Files
- **Backend**: .controller.ts, .service.ts, .guard.ts, .module.ts, schema.prisma
- **Frontend**: .tsx, .ts (components, pages)
- **Mobile**: .dart, .swift, .kt
- **Infra**: Dockerfile, docker-compose, .yml, .env

### Phase 2: Security Audit
Apply carespace-security-auditor checklist by file type. Focus:
- PHI exposure (logging, storage, responses)
- Auth gaps (missing guards, JWT)
- Injection (Prisma, XSS)
- Secrets (hardcoded vs Key Vault)
- HIPAA compliance

### Phase 3: Code Quality
- Missing error handling, TypeScript any usage, null checks
- Missing tests for new endpoints
- Breaking API changes

### Phase 4: Score
- Any Critical → BLOCK
- Any High → NEEDS CHANGES
- Only Medium/Low or clean → PASS

## COMMENT FORMAT

```markdown
## 🔒 Security Review — {PASS|NEEDS CHANGES|BLOCK}

**PR:** {repo}#{number} — {title}
**Files:** {count} | +{additions} -{deletions}

### Security Findings
{findings or "✅ No security issues found."}

### Code Quality
{notes or "✅ Code quality looks good."}

---
*Automated review by CareSpace SecDevOps AI*
```
