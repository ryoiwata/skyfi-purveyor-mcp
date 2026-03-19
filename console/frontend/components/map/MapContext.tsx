"use client";

import {
  createContext,
  useCallback,
  useContext,
  useRef,
  type ReactNode,
} from "react";
import type { Map as MaplibreMap } from "maplibre-gl";
import { parse as parseWkt } from "wellknown";
import bbox from "@turf/bbox";
import centroid from "@turf/centroid";

// ---------------------------------------------------------------------------
// MapAction union — extend here as new days add features
// ---------------------------------------------------------------------------

export type MapAction =
  | { type: "FLY_TO"; center: [number, number]; zoom?: number }
  | { type: "DRAW_AOI"; wkt: string; label?: string }
  | { type: "CLEAR_AOI" };

// ---------------------------------------------------------------------------
// Context value
// ---------------------------------------------------------------------------

interface MapContextValue {
  /** Called once by MapPanel after the MapLibre instance is ready. */
  registerMap: (map: MaplibreMap) => void;
  /** Dispatch a map action. Safe to call before the map is ready (no-ops). */
  dispatch: (action: MapAction) => void;
}

const MapContext = createContext<MapContextValue | null>(null);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function safeRemoveLayer(map: MaplibreMap, id: string) {
  if (map.getLayer(id)) map.removeLayer(id);
}

function safeRemoveSource(map: MaplibreMap, id: string) {
  if (map.getSource(id)) map.removeSource(id);
}

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export function MapContextProvider({ children }: { children: ReactNode }) {
  const mapRef = useRef<MaplibreMap | null>(null);

  const registerMap = useCallback((map: MaplibreMap) => {
    mapRef.current = map;
  }, []);

  const dispatch = useCallback((action: MapAction) => {
    const map = mapRef.current;
    if (!map) return;

    switch (action.type) {
      case "FLY_TO": {
        map.flyTo({ center: action.center, zoom: action.zoom ?? 12, duration: 1500 });
        break;
      }

      case "DRAW_AOI": {
        // Parse WKT → GeoJSON geometry
        let geometry;
        try {
          geometry = parseWkt(action.wkt);
        } catch {
          console.warn("MapContext: failed to parse WKT", action.wkt);
          return;
        }
        if (!geometry) return;

        const geojsonFeature = {
          type: "Feature" as const,
          geometry,
          properties: {},
        };

        // Tear down existing AOI layers/sources
        safeRemoveLayer(map, "aoi-label");
        safeRemoveLayer(map, "aoi-line");
        safeRemoveLayer(map, "aoi-fill");
        safeRemoveSource(map, "aoi-label-source");
        safeRemoveSource(map, "aoi");

        // Add source
        map.addSource("aoi", { type: "geojson", data: geojsonFeature });

        // Fill (light blue)
        map.addLayer({
          id: "aoi-fill",
          type: "fill",
          source: "aoi",
          paint: { "fill-color": "#3b82f6", "fill-opacity": 0.12 },
        });

        // Outline
        map.addLayer({
          id: "aoi-line",
          type: "line",
          source: "aoi",
          paint: { "line-color": "#3b82f6", "line-width": 2 },
        });

        // Fit map to AOI bounds
        const bounds = bbox(geojsonFeature) as [number, number, number, number];
        map.fitBounds(
          [
            [bounds[0], bounds[1]],
            [bounds[2], bounds[3]],
          ],
          { padding: 60, duration: 1200 }
        );

        // Optional text label at centroid
        if (action.label) {
          const centerPoint = centroid(geojsonFeature);
          map.addSource("aoi-label-source", {
            type: "geojson",
            data: {
              type: "FeatureCollection",
              features: [
                {
                  type: "Feature",
                  geometry: centerPoint.geometry,
                  properties: { label: action.label },
                },
              ],
            },
          });
          map.addLayer({
            id: "aoi-label",
            type: "symbol",
            source: "aoi-label-source",
            layout: {
              "text-field": ["get", "label"],
              "text-size": 13,
              "text-anchor": "center",
            },
            paint: {
              "text-color": "#1e40af",
              "text-halo-color": "#ffffff",
              "text-halo-width": 2,
            },
          });
        }
        break;
      }

      case "CLEAR_AOI": {
        safeRemoveLayer(map, "aoi-label");
        safeRemoveLayer(map, "aoi-line");
        safeRemoveLayer(map, "aoi-fill");
        safeRemoveSource(map, "aoi-label-source");
        safeRemoveSource(map, "aoi");
        break;
      }
    }
  }, []);

  return (
    <MapContext.Provider value={{ registerMap, dispatch }}>
      {children}
    </MapContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useMapContext(): MapContextValue {
  const ctx = useContext(MapContext);
  if (!ctx) throw new Error("useMapContext must be used inside MapContextProvider");
  return ctx;
}
