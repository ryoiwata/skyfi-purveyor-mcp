"""SkyFi API constants shared across Purveyor tools."""

from __future__ import annotations

# AOI size limits for order creation (tasking and archive orders)
SKYFI_MIN_AOI_KM2: float = 5.0
SKYFI_MAX_AOI_KM2: float = 10_000.0

# AOI limits for archive searches (more permissive than order limits)
SKYFI_MAX_AOI_VERTICES: int = 500
SKYFI_MAX_SEARCH_AOI_KM2: float = 500_000.0
