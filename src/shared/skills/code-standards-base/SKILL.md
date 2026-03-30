---
name: carespace-security-standards
version: 2.0.0
type: abstract
description: Security standards for CareSpace AI — a HIPAA-compliant movement health platform handling PHI via computer vision.
tags: [security, hipaa, healthcare, carespace, standards]
---

# CareSpace Security Standards

## GUARD

> This is a reference skill. Do not invoke directly.

## ABOUT CARESPACE

CareSpace AI is a HIPAA-compliant movement health platform that uses phone/webcam computer vision to measure 553+ body landmarks. It processes Protected Health Information (PHI): patient identifiers, health assessments, body scan imagery.

**Stack:** React 18/TypeScript + NestJS/Prisma + Flutter/Dart SDK + Swift iOS + Kotlin Android. Azure (Container Apps, ACR, Blob, Service Bus, Key Vault). Auth via FusionAuth + JWT + NestJS guards.

---

## [SUMMARY]

**PHI Rules:** Never log PHI. Tokens in-memory only. TLS enforced. Scan images never on disk. JWT masked in output.

**OWASP Healthcare:** SQL Injection (Prisma), XSS (React), CSRF, Broken Auth (FusionAuth/JWT), Misconfig (Azure), Data Exposure, Access Control (NestJS guards), Deserialization (DTO validation), Logging (audit without PHI content).

**CareSpace Patterns:** FusionAuth JWT validation, NestJS AuthGuard on every endpoint, Prisma parameterized queries, Azure Key Vault for secrets, MediaPipe model integrity, Service Bus PHI encryption.

---

## [FULL]

### HIPAA in Code

- Never hardcode patient data, even in tests — use faker/mock
- Redact from logs: userId, patientId, sessionId, email, password, token, authorization, x-api-key, screenshot, image, base64, firstName, lastName, fullName, name
- JWT tokens: replace with [JWT ***]
- Production: suppress all logging

### HIPAA in Storage

- Tokens: in-memory only, never SharedPreferences/localStorage/disk
- Persistent storage: flutter_secure_storage (iOS Keychain / Android EncryptedSharedPreferences)
- Body scans: base64 in memory → upload → free. Never written to device.

### HIPAA in Transit

- All API calls: https:// enforced (assert + throw)
- Bearer token + x-api-key on every request
- No certificate bypass in production

### OWASP (CareSpace Context)

1. **SQL Injection** — Prisma only. Never raw SQL with string interpolation. Use $queryRaw with tagged templates.
2. **XSS** — React auto-escapes. Never dangerouslySetInnerHTML. CSP headers. Sanitize patient notes.
3. **CSRF** — NestJS CSRF tokens. FusionAuth Origin validation. SameSite cookies.
4. **Broken Auth** — FusionAuth JWT: validate signature, expiry, issuer, audience. Refresh rotation. Rate limiting. @UseGuards(AuthGuard) on every controller.
5. **Misconfig** — No debug in production. No Swagger in production. No wildcard CORS. No public blob containers for PHI.
6. **Data Exposure** — Azure Key Vault for secrets. .env gitignored. No secrets in Dockerfile. Prisma connection from env. Error responses hide internals.
7. **Access Control** — AuthGuard + RolesGuard. Patients access own data only. Clinician role-based. Admin guard separate.
8. **Deserialization** — class-validator + class-transformer in NestJS DTOs. Validate API responses in Flutter.
9. **Logging** — Log auth events + PHI access metadata. Never log PHI content.
10. **Dependencies** — npm/pub audit. Pin versions. Monitor CVEs for TensorFlow.js, MediaPipe, Prisma, NestJS, Flutter.

### Azure Security

- Container Apps: no SSH, secrets via Key Vault refs, HTTPS-only ingress
- Blob Storage: private containers for PHI, SAS with min permissions, encryption at rest
- Service Bus: encrypt PHI messages, monitor dead-letter queue
