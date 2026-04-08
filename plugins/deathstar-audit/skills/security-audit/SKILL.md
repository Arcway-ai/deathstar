---
name: security-audit
description: Use this skill when conducting a security audit, vulnerability assessment, or security review of a codebase. Activates when the user asks to audit, scan, or assess security posture.
version: 1.1.0
---

# Security Audit Methodology

You are conducting a structured security audit. Follow this methodology systematically rather than skimming the codebase. Depth over breadth — it is better to find 3 real vulnerabilities than 20 false positives.

## Phase 1: Reconnaissance

Before analyzing code, understand the attack surface:

1. **Identify entry points** — HTTP routes, WebSocket endpoints, CLI commands, file uploads, IPC
2. **Map trust boundaries** — Where does user input enter? Where does data cross privilege levels?
3. **Catalog dependencies** — Check `package.json`, `pyproject.toml`, `go.mod`, `Cargo.toml` for known CVEs
4. **Review configuration** — Environment variables, config files, secrets management, default values

## Phase 2: OWASP Top 10 Assessment

Check each category systematically. For each finding, cite the exact file and line.

### A01: Broken Access Control
- Are authorization checks present on every endpoint?
- Can users access resources belonging to other users?
- Are there path traversal vulnerabilities in file operations?
- Do API endpoints enforce role-based access correctly?

### A02: Cryptographic Failures
- Are secrets hardcoded or logged?
- Is sensitive data encrypted at rest and in transit?
- Are cryptographic algorithms current (no MD5/SHA1 for security)?
- Are API keys, tokens, and passwords properly managed?

### A03: Injection
- SQL: Are queries parameterized? Any string concatenation in queries?
- Command: Is `subprocess` called with `shell=True`? Are args sanitized?
- XSS: Is user input rendered without escaping? `innerHTML`, `dangerouslySetInnerHTML`?
- Template: Are template engines configured for auto-escaping?
- Path: Are file paths validated against traversal (`..`, symlinks)?

### A04: Insecure Design
- Are there rate limits on authentication endpoints?
- Is there account lockout after failed attempts?
- Are business logic flows protected against abuse?

### A05: Security Misconfiguration
- Are debug modes disabled in production?
- Are default credentials changed?
- Are error messages leaking stack traces or internal details?
- Are security headers set (CSP, HSTS, X-Frame-Options)?
- Are CORS policies restrictive enough?

### A06: Vulnerable Components
- Run `npm audit` / `pip audit` / equivalent mentally — flag outdated deps
- Are there dependencies with known CVEs?
- Are dependency versions pinned?

### A07: Authentication Failures
- How are sessions managed? Are tokens signed and validated?
- Is password hashing using bcrypt/scrypt/argon2 (not SHA/MD5)?
- Are JWTs validated properly (algorithm, expiry, issuer)?
- Is there protection against credential stuffing?

### A08: Data Integrity Failures
- Are CI/CD pipelines protected against tampering?
- Are software updates verified with signatures?
- Is deserialization of untrusted data avoided (pickle, yaml.load)?

### A09: Logging & Monitoring Failures
- Are security events logged (failed logins, authorization failures)?
- Are logs protected against injection?
- Are sensitive values excluded from logs?

### A10: Server-Side Request Forgery (SSRF)
- Are outbound HTTP requests validated against allow-lists?
- Can user input control destination URLs?
- Are internal services accessible via SSRF?

## Phase 3: Secrets & Credential Scanning

Search for patterns that indicate leaked secrets:
- API keys: `AKIA[A-Z0-9]{16}`, `sk-[a-zA-Z0-9]{32,}`
- Private keys: `-----BEGIN.*PRIVATE KEY-----`
- Connection strings with embedded passwords
- `.env` files committed to version control
- Hardcoded tokens in source code

## Phase 4: Dependency Analysis

For each dependency file found:
1. Identify dependencies with broad permissions or large attack surface
2. Flag dependencies that haven't been updated in >1 year
3. Note any dependencies pulled from non-standard registries

## Output Format — STRICT

**Your final response MUST be a single JSON object** matching the schema below. Do NOT wrap it in markdown code fences. Do NOT include any text before or after the JSON. The UI parses this JSON to render an interactive review panel with per-finding actions.

```json
{
  "summary": "1-3 sentence summary of the security posture and key vulnerabilities found",
  "verdict": "approve | request_changes | comment",
  "findings": [
    {
      "id": "finding-1",
      "file": "path/to/file.ext",
      "line_start": 42,
      "line_end": 45,
      "severity": "error | warning | suggestion | nitpick",
      "title": "Short description of the vulnerability",
      "body": "Detailed explanation: what the vulnerability is, why it matters, what an attacker could achieve, and the OWASP category (e.g. A03 Injection). Include evidence — the specific code pattern or configuration that creates the vulnerability.",
      "original_code": "the vulnerable code snippet (or null if not applicable)",
      "suggested_code": "the remediated code snippet (or null if no concrete fix)"
    }
  ]
}
```

### Field Guidelines

- **summary**: Concise overview of the security posture. Mention the most critical finding and overall risk level.
- **verdict**: `approve` = no security issues found, passes audit. `request_changes` = has error/warning findings that must be remediated. `comment` = has suggestions for hardening but nothing exploitable.
- **severity mapping**: `error` = CRITICAL/HIGH (RCE, auth bypass, data breach, injection). `warning` = MEDIUM (info disclosure, missing controls, weak crypto). `suggestion` = LOW (best practice violations). `nitpick` = INFO (hardening recommendations).
- **line_start / line_end**: Use `null` if the finding is about configuration or architecture rather than specific lines.
- **original_code / suggested_code**: Include working remediation code when possible. Use `null` when the fix is architectural.
- If no vulnerabilities are found, return `{"summary": "No vulnerabilities found — [brief note on what was audited]", "verdict": "approve", "findings": []}`.

## Rules

- Never report a finding you aren't confident about. False positives erode trust.
- Always include the exact file path and line number in the `file` and `line_start` fields.
- Provide working remediation code in `suggested_code`, not just descriptions.
- Prioritize findings by exploitability, not just theoretical severity.
- If you find no vulnerabilities in a category, that's fine — only report real findings.
- **Output ONLY the JSON object.** No preamble, no markdown fences, no commentary after. The UI will not render the audit panel if the output is not valid JSON.
