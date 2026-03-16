# Session Log: Diagnosing and Fixing Intermittent 500 on Confirmation Page

**Date:** 2026-03-14 15:07 CST
**Duration:** ~45 minutes
**Focus:** Root-cause the intermittent 500 on `POST /confirm/{token}` and deploy a fix

---

## What Got Done

- Ran `aws ecs list-tasks` — confirmed only 1 ECS task running (ruled out multi-task Fernet key mismatch)
- Tailed `/ecs/purveyor` CloudWatch logs (24h window) to find actual 500 tracebacks
- Identified the full exception: `httpx.HTTPStatusError: Client error '422 Unprocessable Entity' for url 'https://app.skyfi.com/platform-api/order-archive'`
- Confirmed the 500 was escaping `confirm_order` uncaught (Bug 1, already fixed in v1.1.3/v1.1.4 via commit `13b7bf1`)
- Identified the underlying cause of the 422: `model_dump_skyfi()` was sending `{"deliveryDriver": "NONE"}` — SkyFi rejects that value, the field must be absent (Bug 2)
- Fixed `ArchiveOrderRequest.model_dump_skyfi()` and `TaskingOrderRequest.model_dump_skyfi()` to pop `deliveryDriver` and `deliveryParams` from the payload when driver is `NONE`
- Added 3 regression tests in `tests/test_skyfi_client.py` covering: NONE driver excluded (archive), NONE driver excluded (tasking), real driver included
- All 279 passing tests continue to pass
- Built and pushed Docker image `v1.1.5` to ECR
- Updated `deploy/terraform/aws/terraform.tfvars` to `image_tag = "v1.1.5"`
- Ran `terraform apply` to register new task definition and update ECS service
- Waited for `aws ecs wait services-stable` — confirmed stable
- Verified `/health` returns `{"status": "healthy", "database": "ok", "skyfi_api": "ok"}`
- Committed: `fix(core): omit deliveryDriver from SkyFi order requests when driver is NONE` (`086bbc2`)
- Committed: `chore(deploy): bump image_tag to v1.1.5` (`d763bd9`)

---

## Issues & Troubleshooting

### The intermittent 500 on POST /confirm/{token}

- **Problem:** Clicking "Confirm" on the order confirmation page intermittently returned a raw 500 Internal Server Error instead of either success or a user-friendly error page.
- **Cause (Bug 1 — already fixed):** `confirm_order` in `confirmation.py` had a `try/finally` block but no `except httpx.HTTPStatusError`. When SkyFi returned any 4xx/5xx error, the `httpx.HTTPStatusError` propagated past the `except ToolError` handler in `post_confirmation_action` → unhandled exception → raw 500. Fixed in commit `13b7bf1` (shipped in v1.1.3, included in v1.1.4).
- **Cause (Bug 2 — fixed this session):** `model_dump_skyfi()` on both `ArchiveOrderRequest` and `TaskingOrderRequest` serialized `DeliveryDriver.NONE` as the string `"NONE"` and sent `{"deliveryDriver": "NONE"}` to SkyFi. SkyFi's API does not accept `"NONE"` as a valid driver value — when no delivery is configured the field must be absent entirely. This caused SkyFi to return 422 on every archive and tasking order attempt that used the default (no-delivery) configuration, which in turn triggered Bug 1.
- **Fix:** Added a post-processing step in `model_dump_skyfi()` for both request classes: after `model_dump(by_alias=True, exclude_none=True, mode="json")`, pop `deliveryDriver` and `deliveryParams` from the dict if `deliveryDriver == "NONE"`.

### Secondary: 410 "record not found" on GET /confirm/{token}

- **Problem:** Some confirmation page visits returned 410 with "record not found" even for recently created confirmations.
- **Cause:** The user/agent was clicking a URL from a *previous* confirmation (different Fernet token, different DB record) rather than the most recently generated one. Hash verification confirmed FastAPI was correctly URL-decoding `%3D` → `=`, and the hash of the visited token (`83bc002078cfd67d`) did not match the hash of the most recently created token (`3a501a16174fbe13`) — they were completely different tokens.
- **Fix:** No code change needed. The 410 response with "invalid or expired" message is correct behavior for stale URLs. Likely the ADK agent was re-presenting an older URL from conversation history.

### terraform plan showed "no changes" initially

- **Problem:** Running `terraform plan` in the terraform subdirectory showed no changes despite updating `terraform.tfvars` to `v1.1.5`.
- **Cause:** The `terraform` command was run from the wrong working directory (project root instead of `deploy/terraform/aws/`).
- **Fix:** Changed to the correct directory before running `terraform plan` / `terraform apply`.

---

## Decisions Made

- **Strip `deliveryDriver`/`deliveryParams` at serialization time, not at the model level.** The `NONE` sentinel needs to exist in the Pydantic model so Python code can reason about delivery state internally. The fix is at the API boundary (`model_dump_skyfi()`), not at the field default. This keeps the model semantics clean.

- **Fix both `ArchiveOrderRequest` and `TaskingOrderRequest`.** Both classes have the same `delivery_driver: DeliveryDriver = Field(default=DeliveryDriver.NONE, ...)` and the same `model_dump_skyfi()` pattern. Applied the fix symmetrically rather than only fixing the archive path where the 422 was observed.

- **Did not change the `NONE` enum value or the field default.** The `NONE` sentinel is used in `orders.py` for driver selection logic and is needed for `model_validate` round-trips. Removing it would break more things.

---

## Current State

- **Deployed:** `v1.1.5` on ECS Fargate (`us-east-1`), 1 task running, service stable
- **Health:** `{"status": "healthy", "database": "ok", "skyfi_api": "ok", "redis": "skipped"}`
- **500 bug:** Fixed. Archive and tasking order confirmations no longer send `deliveryDriver: "NONE"` to SkyFi; the field is now absent when no delivery is configured. SkyFi should accept these orders.
- **Error handling:** If SkyFi returns any other 4xx/5xx (e.g., insufficient budget, 402), the `except httpx.HTTPStatusError` in `confirm_order` (added in `13b7bf1`) converts it to a ToolError → `post_confirmation_action` returns a 502 error page with the SkyFi message instead of a raw 500.
- **Stale URL 410s:** No code change. The behavior is correct; the issue is agent/user UX.
- **Branch:** `feat/tier2-auth-user-urls`

---

## Next Steps

1. **End-to-end smoke test** — ask the ADK agent to search archives and place an order; verify the confirmation page renders, the "Confirm" button places the order successfully, and the success page shows the SkyFi order ID.
2. **Investigate stale URL UX** — if the ADK agent is frequently presenting old confirmation URLs to users, consider adding a clearer error message on the 410 page (e.g., "This link is expired. Ask your AI assistant for a new confirmation link.") or having the agent re-generate rather than retry.
3. **Add test for `confirm_order` 422 handling** — a respx-mocked test that verifies a SkyFi 422 on `POST /order-archive` during confirmation results in a 502 error page (not a 500), exercising the `except httpx.HTTPStatusError` path in `confirmation.py`.
4. **Monitor logs** — tail `/ecs/purveyor` after the next ADK agent order attempt to confirm no 500s and that the order placement succeeds end-to-end.
