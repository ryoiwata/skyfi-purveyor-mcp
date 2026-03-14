# Session Log: Expired Confirmation Link Root Cause & Fix

**Date:** 2026-03-14 14:09
**Duration:** ~2.5 hours
**Focus:** Diagnose and fix "Link Expired" (410) shown immediately when clicking freshly-created confirmation URLs on the ECS deployment

---

## What Got Done

- Added structured diagnostic logs to `src/purveyor/app.py` GET `/confirm/{token}` handler:
  - `confirm_page_lookup` — logs `token_len`, `token_prefix`, `token_hash_prefix`, `fernet_key_fingerprint`
  - `confirm_page_record_not_found` — logs `token_hash_prefix`
  - `confirm_page_decrypt_failed` — logs `token_hash_prefix`, `record_status`
- Added `fernet_key_fingerprint` and `token_hash_prefix` fields to `tasking_order_confirmation_created` and `archive_order_confirmation_created` log events in `src/purveyor/tools/orders.py`
- Added explicit `try/except` around token encryption and DB write in both `create_tasking_order` and `create_archive_order` so failures surface in CloudWatch instead of being swallowed silently by FastMCP
- Fixed `CONFIRMATION_BASE_URL` in `deploy/terraform/aws/main.tf` — was constructing `"https://"` (broken empty string) when `var.domain` was unset; now correctly falls back to `"http://${aws_lb.main.dns_name}"`
- Added `default = ""` to `var.domain` and `var.acm_certificate_arn` in `deploy/terraform/aws/variables.tf`
- Created `tests/test_confirmation_page.py` — 9 integration tests for `GET/POST /confirm/{token}` using module-scoped fixtures to avoid `StreamableHTTPSessionManager` single-use constraint
- Fixed the root cause: added `from urllib.parse import quote` and changed both `confirmation_url` constructions in `orders.py` to `f"{base}/confirm/{quote(token, safe='')}"` — percent-encodes the Fernet token before embedding in the URL
- Deployed Docker images v1.1.3 (diagnostics) and v1.1.4 (fix) to ECR and ECS Fargate via Terraform
- Removed pre-existing unused `lc` variable lint errors in `list_orders` and `request_redelivery`
- Committed all changes across 4 commits: diagnostic logging, fix, and two `terraform.tfvars` version bumps

---

## Issues & Troubleshooting

### Problem 1: "Link Expired" on fresh confirmation URLs

- **Problem:** Every confirmation URL returned by the agent showed "This order link is invalid or has expired" (HTTP 410) immediately after creation — even seconds after the MCP tool returned it.
- **Cause:** Unknown at start of session. Three candidate failure paths:
  - Case A: Token hash stored in DB ≠ hash computed from URL token (DB miss)
  - Case B: Fernet 30-minute TTL already expired (impossible in seconds)
  - Case C: Fernet key mismatch between MCP lifespan and FastAPI lifespan (different `CONFIRMATION_SECRET_KEY` instances)
- **Diagnostic approach:** Added `fernet_key_fingerprint` (SHA-256 of key bytes, first 8 hex chars) and `token_hash_prefix` (first 16 hex chars of SHA-256 of token) to both the creation log (MCP lifespan) and the confirm-page lookup log (FastAPI lifespan). Deployed v1.1.3 and triggered a real order.
- **CloudWatch output:**
  ```
  archive_order_confirmation_created: fernet_key_fingerprint=4ff04ab7  token_hash_prefix=074b5ecec18d4549
  confirm_page_lookup:                fernet_key_fingerprint=4ff04ab7  token_hash_prefix=659ae371945c2d2d
  confirm_page_record_not_found:      token_hash_prefix=659ae371945c2d2d
  ```
- **Cause confirmed:** Same Fernet key (`4ff04ab7` on both sides) — key mismatch ruled out. Different token hashes — the token itself was being **corrupted** between generation and browser click. The Fernet token uses URL-safe base64 which contains `_` characters. The ADK web UI renders Gemini's response as Markdown. Gemini outputs the raw confirmation URL as plain text; the Markdown renderer treats `_..._` sequences inside the URL as emphasis markers and **strips the underscores**, producing a different string with a different SHA-256 hash that doesn't match the DB record.
- **Fix:** `quote(token, safe='')` percent-encodes `_` → `%5F` and `=` → `%3D` before embedding the token in the URL. Starlette automatically URL-decodes path parameters, so the handler receives the original token intact. Fernet decryption and DB lookup succeed normally.

### Problem 2: `StreamableHTTPSessionManager` single-use constraint in tests

- **Problem:** Initial `test_confirmation_page.py` created a new app instance per test function. The second test failed with `StreamableHTTPSessionManager .run() can only be called once per instance`.
- **Cause:** FastMCP's `StreamableHTTPSessionManager` is designed for a single `.run()` call. Creating a new app per test hit this constraint.
- **Fix:** Switched all fixtures in `test_confirmation_page.py` to `scope="module"` — all 9 tests share one app instance and one TestClient for the duration of the module.

### Problem 3: Unused `lc` variable lint errors in `orders.py`

- **Problem:** `uv run ruff check` reported `F841 Local variable 'lc' is assigned to but never used` in `list_orders` and `request_redelivery`.
- **Cause:** Pre-existing dead code — `lc` was assigned but never referenced.
- **Fix:** Removed the unused assignments.

---

## Decisions Made

- **Diagnostic-first approach before fixing.** Rather than guessing the root cause (key mismatch vs. DB miss vs. token corruption), added structured logging to both the write path (MCP lifespan) and read path (FastAPI lifespan) so the CloudWatch logs would definitively identify which case was occurring. This avoided shipping a wrong fix.

- **Fernet key fingerprint via SHA-256 of key bytes.** To compare key identity without leaking the key itself, logged `hashlib.sha256(settings.fernet_key).hexdigest()[:8]`. Eight hex chars (32 bits) is enough to confirm identity or detect mismatch, far too short to reconstruct the key.

- **URL-encode at generation, not at routing.** The fix is applied in `orders.py` where the URL is constructed, not in the FastAPI route. The route handler stays unchanged — Starlette's automatic path-param URL-decoding is the mechanism that makes this transparent end-to-end.

- **Module-scoped pytest fixtures** for confirmation page tests to work around the `StreamableHTTPSessionManager` single-use constraint. This is the right tradeoff: tests share one app instance (acceptable for integration tests) vs. having to restructure the entire server startup lifecycle.

- **Kept path-parameter URL structure** (rather than switching to query param `?token=`). Percent-encoding the token in the path is a smaller change, and Starlette handles it correctly as confirmed by the new `test_token_hash_identical_after_percent_encoded_url_path` test.

---

## Current State

**Working:**
- ECS Fargate deployment running v1.1.4 at `http://purveyor-691022321.us-east-1.elb.amazonaws.com`
- Health endpoint returning healthy
- MCP tools accessible from ADK agent
- Confirmation URLs now built with percent-encoded tokens — should survive Markdown rendering
- Fernet key consistent across MCP and FastAPI lifespans (confirmed by diagnostic logs)
- `CONFIRMATION_BASE_URL` correctly set to ALB DNS in ECS environment
- 9 integration tests for the confirmation flow, all passing

**Deployed image:** v1.1.4
**Git branch:** `feat/tier2-auth-user-urls` (ahead of origin by 6 commits from this session)

**Not yet verified:**
- End-to-end confirmation flow with v1.1.4 deployed — the fix is in place and logically sound, but hasn't been click-tested yet with the new image live.

---

## Next Steps

1. **Verify the fix end-to-end.** Run the ADK agent, create an archive or tasking order, click the confirmation URL — confirm the order details page renders (200) and the Confirm button works.
2. **Check CloudWatch after the test.** `confirm_page_lookup` should now show matching `token_hash_prefix` values on both the creation log and the lookup log.
3. **Strip diagnostic verbosity if desired.** The `token_prefix`, `token_hash_prefix`, and `fernet_key_fingerprint` fields added for debugging can be kept (useful for future incidents) or removed to reduce log noise. Recommend keeping them.
4. **Push the branch and open a PR.** Six commits of meaningful work on `feat/tier2-auth-user-urls` are not yet pushed to origin.
5. **Add POST `/confirm/{token}` percent-encoded round-trip test for confirm and cancel actions** (the new test only covers GET; the POST paths are implicitly covered but not with a percent-encoded URL).
