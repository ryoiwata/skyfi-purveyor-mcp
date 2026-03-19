"use client";

import { useEffect } from "react";
import { toolResultEmitter } from "@/lib/tool-emitter";
import { useMapContext, type MapAction } from "./MapContext";
import type { ArchiveResult } from "@/types/sse-events";

// ---------------------------------------------------------------------------
// Tool output type helpers
// ---------------------------------------------------------------------------

function parseOutput(output: unknown): Record<string, unknown> | null {
  if (typeof output === "string") {
    try {
      return JSON.parse(output) as Record<string, unknown>;
    } catch {
      return null;
    }
  }
  if (output !== null && typeof output === "object") {
    return output as Record<string, unknown>;
  }
  return null;
}

/**
 * Map a Purveyor tool result to one or more MapActions.
 *
 * Tool output shapes:
 *   geocode_location      → { coordinates: [lat, lon], aoi_wkt, display_name }
 *   create_aoi_from_point → { aoi_wkt, actual_area_sq_km }
 *   calculate_aoi_area    → { area_sq_km, vertex_count, is_valid } (no new drawing needed)
 *   search_archives       → { archives: ArchiveResult[], total, ... }
 *   get_archive_details   → { archive_id, footprint, ... } (single archive)
 */
function getMapActions(tool: string, output: unknown): MapAction[] {
  const data = parseOutput(output);
  if (!data) return [];

  switch (tool) {
    case "geocode_location": {
      const aoi_wkt = data.aoi_wkt as string | undefined;
      const display_name = data.display_name as string | undefined;
      if (aoi_wkt) {
        return [{ type: "DRAW_AOI", wkt: aoi_wkt, label: display_name }];
      }
      // Fallback: fly to coordinates if no AOI
      const coords = data.coordinates as [number, number] | undefined;
      if (Array.isArray(coords) && coords.length === 2) {
        // Purveyor returns [lat, lon]; MapLibre wants [lon, lat]
        return [{ type: "FLY_TO", center: [coords[1], coords[0]], zoom: 12 }];
      }
      return [];
    }

    case "create_aoi_from_point": {
      const aoi_wkt = data.aoi_wkt as string | undefined;
      if (aoi_wkt) {
        return [{ type: "DRAW_AOI", wkt: aoi_wkt }];
      }
      return [];
    }

    case "search_archives": {
      const archives = data.archives as ArchiveResult[] | undefined;
      if (Array.isArray(archives) && archives.length > 0) {
        return [{ type: "PLOT_ARCHIVES", archives }];
      }
      return [];
    }

    case "get_archive_details": {
      // Single archive object — highlight it on the map
      const archive_id = data.archive_id as string | undefined;
      if (archive_id) {
        return [{ type: "HIGHLIGHT_ARCHIVE", archiveId: archive_id }];
      }
      return [];
    }

    default:
      return [];
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Invisible component that bridges SSE tool results to MapContext dispatch.
 * Must be rendered inside both MapContextProvider and the chat runtime.
 */
export function MapSync() {
  const { dispatch } = useMapContext();

  useEffect(() => {
    const unsubscribe = toolResultEmitter.subscribe(({ tool, output }) => {
      const actions = getMapActions(tool, output);
      actions.forEach((action) => dispatch(action));
    });

    return unsubscribe;
  }, [dispatch]);

  return null;
}
