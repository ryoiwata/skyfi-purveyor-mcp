# Session Log: OpenStreetMap Tools Integration

**Date:** 2026-03-15 20:30
**Duration:** ~1 hour
**Focus:** Add three new MCP tools (search_osm, get_osm_boundary, get_osm_features_in_area) backed by Nominatim and Overpass APIs

---

## What Got Done

- **Created `src/purveyor/tools/osm.py`** — new module with three MCP tools and all supporting helpers:
  - `search_osm` — Nominatim search returning WKT polygon + area for any named feature
  - `get_osm_boundary` — admin boundary lookup (city/state/country) with admin_level filtering
  - `get_osm_features_in_area` — Overpass API query for typed features (airports, ports, stadiums, etc.) within a radius
  - Sync helpers: `_geojson_to_wkt`, `_calculate_area_sq_km`, `_build_way_polygon`, `_haversine_km`
  - Async HTTP helpers: `_nominatim_search`, `_nominatim_search_boundary`, `_overpass_query` (module-level, testable directly)

- **Updated `src/purveyor/server.py`** — imported and registered `register_osm(mcp)` alongside existing tools

- **Updated `agents/google_adk/satellite_imagery_agent/agent.py`** — added OSM tool guidance to agent instruction explaining when to use each tool and to check `area_km2` against SkyFi limits

- **Created `tests/test_osm_tools.py`** — 18 tests covering:
  - `_geojson_to_wkt` with simple polygon, MultiPolygon (takes largest), and complex polygon needing simplification
  - `_build_way_polygon` validity and simplification
  - `_haversine_km` zero distance, known distance (Austin→NYC), always non-negative
  - `_calculate_area_sq_km` positive and non-negative guarantees
  - `_nominatim_search` and `_nominatim_search_boundary` with mocked httpx responses
  - `_overpass_query` with mocked httpx response and HTTP error → ToolError
  - WKT validity guarantee across all GeoJSON fixtures
  - Vertex limit guarantee for simplified polygons at n=501, 600, 1000, 2000
  - 2 live tests behind `@pytest.mark.live` (skipped in CI)

- **Committed** as `feat(tools): add OpenStreetMap integration tools` on branch `feat/openstreetmap`

---

## Issues & Troubleshooting

- **Problem:** `search_osm` tool not found when tested in Google ADK dev UI (`Tool 'search_osm' not found. Available tools: geocode_location, ...`)
  - **Cause:** The ADK agent's `PURVEYOR_URL` defaults to the deployed AWS ELB (`purveyor-691022321.us-east-1.elb.amazonaws.com`), which is running the old `v1.2.0` image. The new tools only exist in the local codebase on the `feat/openstreetmap` branch.
  - **Fix:** Two paths — (1) run a local Purveyor server (`uv run purveyor serve --local --reload`) and point the ADK agent at it with `PURVEYOR_URL=http://localhost:8000`; or (2) merge the branch, tag `v1.3.0`, let CI build/push the Docker image, then bump `image_tag` in Terraform and apply.

- **Problem:** ruff reported `RUF001` (ambiguous EN DASH character) in summary strings and docstrings
  - **Cause:** Used Unicode en-dash (`–`) in f-strings and docstrings (e.g., `"5–10,000 km²"`)
  - **Fix:** Replaced with ASCII hyphen (`-`) and plain `km2` to avoid the Unicode character

- **Problem:** ruff reported `RUF059` (unpacked variable `note` never used) in test
  - **Cause:** `wkt, note = _geojson_to_wkt(...)` where `note` wasn't referenced in the assertion
  - **Fix:** Renamed to `wkt, _note = ...`

- **Problem:** Python `SyntaxError` potential with optional parameters before `ctx: McpContext`
  - **Cause:** Python forbids a non-default positional parameter after parameters with defaults (e.g., `feature_type: str | None = None, limit: int = 5, ctx: McpContext` would be a SyntaxError)
  - **Fix:** Used `*, ctx: McpContext` (keyword-only separator) so `ctx` is a required keyword-only parameter after the defaults. Verified FastMCP handles this correctly by running tool registration in a test process — all three tools registered successfully.

---

## Decisions Made

- **Share `_nominatim_semaphore` from `geospatial.py`** rather than creating a new one in `osm.py`. Nominatim ToS requires a global 1 req/sec rate limit across all callers; having two independent semaphores would allow simultaneous calls from the two modules. Importing the module-level object from `geospatial.py` ensures they share the same semaphore. (`from purveyor.tools.geospatial import _nominatim_semaphore`)

- **Extract HTTP logic into module-level async functions** (`_nominatim_search`, `_nominatim_search_boundary`, `_overpass_query`) rather than embedding all logic in the tool closures. This makes the HTTP layer directly testable without constructing a mock MCP context, consistent with how `resolve_location` is tested in `test_geospatial.py`.

- **Use `data={"data": query}` for Overpass POST** (URL-encoded form data) rather than `content=` (raw bytes). Overpass API expects the QL query as a form field named `data`.

- **Use `out body center;` in Overpass query** so all elements (ways and relations) carry a `center` lat/lon field from Overpass directly. This avoids having to compute centroids manually for relations, which would require parsing all member ways and their nodes — much more complex.

- **For relations in `get_osm_features_in_area`, only return center point** (no polygon WKT). Full relation geometry requires resolving nested member ways and nodes, which is disproportionately complex. Ways get full polygon WKT; relations get just the center point. This is noted in the implementation comments.

- **Simplify GeoJSON MultiPolygons to the largest polygon by area** rather than taking the convex hull. The largest polygon typically represents the main feature body (e.g., the main island of an archipelago, the main park boundary) while convex hull would include water/gaps between disconnected parts.

- **Area warnings in `get_osm_boundary`** at two thresholds: >500,000 km² (exceeds SkyFi search limit) and >10,000 km² (may exceed order limits). Returns `warning: null` when within limits, so the agent can check the field without string parsing.

---

## Current State

- **Branch:** `feat/openstreetmap` (commit `613ec06`)
- **Local code:** All three OSM tools implemented, tested (18 tests passing), linted (ruff clean), and type-checked (no new mypy errors)
- **Deployed server (AWS ELB):** Still running `v1.2.0` — OSM tools not yet available there
- **Tests:** 18 unit/integration tests passing; 2 live tests gated on `@pytest.mark.live`
- **Agent instruction:** Updated with OSM tool guidance and area limit reminders

---

## Next Steps

1. **Deploy the new tools** — merge `feat/openstreetmap` → `main`, tag `v1.3.0`, wait for CI to build/push Docker image to GHCR, then bump `image_tag` in Terraform and apply to update ECS
2. **Verify end-to-end** — run "Find the boundary of Yellowstone National Park" in ADK dev UI against the updated deployed server and confirm `search_osm` is called and returns a WKT polygon
3. **Consider caching OSM results** — `_nominatim_search` results could be cached (like `resolve_location` does) using the lifespan `cache` object, since park/boundary boundaries rarely change
4. **Test `get_osm_features_in_area` with real data** — run a live query for `aeroway=aerodrome` near LAX to verify Overpass response parsing and polygon building works end-to-end
5. **Consider Overpass rate limiting** — currently no rate limit on Overpass calls; if usage grows, add a module-level semaphore (Overpass allows ~1 req/2sec for public API)
