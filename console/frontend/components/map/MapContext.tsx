"use client";

import {
  createContext,
  useCallback,
  useContext,
  useRef,
  type ReactNode,
} from "react";
import type { Map as MaplibreMap, MapMouseEvent, MapGeoJSONFeature } from "maplibre-gl";
import { Popup } from "maplibre-gl";
import { parse as parseWkt } from "wellknown";
import bbox from "@turf/bbox";
import centroid from "@turf/centroid";
import type { ArchiveResult } from "@/types/sse-events";
import { PROVIDER_COLORS } from "@/components/tools/ArchiveResultCard";

// ---------------------------------------------------------------------------
// MapAction union — extend here as new days add features
// ---------------------------------------------------------------------------

export type MapAction =
  | { type: "FLY_TO"; center: [number, number]; zoom?: number }
  | { type: "DRAW_AOI"; wkt: string; label?: string }
  | { type: "CLEAR_AOI" }
  | { type: "PLOT_ARCHIVES"; archives: ArchiveResult[] }
  | { type: "HIGHLIGHT_ARCHIVE"; archiveId: string }
  | { type: "CLEAR_ARCHIVES" }
  | { type: "FLASH_AOI" };

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

function renderArchivePopup(props: Record<string, unknown>): string {
  const color = String(props.color ?? "#6b7280");
  const provider = String(props.provider ?? "Unknown");
  const resolution = String(props.resolution ?? "");
  const captureDate = String(props.capture_date ?? "");
  const cloud = props.cloud_cover;
  const price = String(props.price ?? "");
  const skyfiUrl = String(props.skyfi_url ?? "#");

  const cloudHtml =
    cloud !== null && cloud !== undefined
      ? `<span style="color:${Number(cloud) < 10 ? "#16a34a" : Number(cloud) < 30 ? "#ca8a04" : "#dc2626"}">
          ☁ ${Number(cloud).toFixed(0)}% cloud
        </span><br/>`
      : "";

  return `
    <div style="font-family:sans-serif;font-size:12px;line-height:1.6;min-width:180px">
      <div style="margin-bottom:4px">
        <span style="background:${color};color:white;padding:1px 6px;border-radius:3px;font-size:10px;font-weight:600">${provider}</span>
        <span style="background:#f1f5f9;color:#334155;padding:1px 5px;border-radius:3px;font-size:10px;margin-left:3px">${resolution}</span>
      </div>
      <div style="color:#374151">
        📅 ${captureDate}<br/>
        ${cloudHtml}
        <strong style="font-size:13px">${price}</strong>
      </div>
      <div style="margin-top:6px;border-top:1px solid #e5e7eb;padding-top:5px">
        <a href="${skyfiUrl}" target="_blank" style="color:#3b82f6;text-decoration:underline">View on SkyFi →</a>
      </div>
    </div>
  `;
}

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export function MapContextProvider({ children }: { children: ReactNode }) {
  const mapRef = useRef<MaplibreMap | null>(null);
  const popupRef = useRef<Popup | null>(null);

  // In-memory lookup for archive features (coords + props) by archive_id
  const archiveCoordsRef = useRef<
    Map<string, { lng: number; lat: number; props: Record<string, unknown> }>
  >(new Map());

  // Track click handler reference so we can remove it before re-adding
  const archiveClickRef = useRef<
    ((e: MapMouseEvent & { features?: MapGeoJSONFeature[] }) => void) | null
  >(null);

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

      case "PLOT_ARCHIVES": {
        // Clean up existing archive layers/sources
        if (archiveClickRef.current) {
          map.off("click", "archives-circles", archiveClickRef.current);
          archiveClickRef.current = null;
        }
        safeRemoveLayer(map, "archives-circles");
        safeRemoveLayer(map, "archives-line");
        safeRemoveLayer(map, "archives-fill");
        safeRemoveSource(map, "archives-points");
        safeRemoveSource(map, "archives");
        archiveCoordsRef.current.clear();

        if (action.archives.length === 0) break;

        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const polygonFeatures: any[] = [];
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const pointFeatures: any[] = [];

        for (const archive of action.archives) {
          let geometry: ReturnType<typeof parseWkt> | null = null;
          try {
            geometry = parseWkt(archive.footprint);
          } catch {
            continue;
          }
          if (!geometry) continue;

          const color = PROVIDER_COLORS[archive.provider] ?? "#6b7280";
          const captureDate = archive.capture_timestamp
            ? new Date(archive.capture_timestamp).toLocaleDateString("en-US", {
                year: "numeric",
                month: "short",
                day: "numeric",
              })
            : "Unknown";

          const props = {
            archive_id: archive.archive_id,
            provider: archive.provider,
            resolution: archive.resolution,
            capture_date: captureDate,
            cloud_cover: archive.cloud_coverage_percent,
            price: archive.open_data
              ? "Free"
              : `$${archive.price_full_scene.toFixed(0)}`,
            skyfi_url: archive.skyfi_preview_url,
            color,
            open_data: archive.open_data,
          };

          polygonFeatures.push({ type: "Feature", geometry, properties: props });

          // Compute centroid for circle marker
          const polygonFeature = { type: "Feature" as const, geometry, properties: {} };
          const center = centroid(polygonFeature as Parameters<typeof centroid>[0]);
          const [lng, lat] = center.geometry.coordinates;
          pointFeatures.push({ type: "Feature", geometry: center.geometry, properties: props });

          // Store in memory for HIGHLIGHT_ARCHIVE lookup
          archiveCoordsRef.current.set(archive.archive_id, { lng, lat, props });
        }

        // Polygon footprint layers
        map.addSource("archives", {
          type: "geojson",
          data: { type: "FeatureCollection", features: polygonFeatures },
        });
        map.addLayer({
          id: "archives-fill",
          type: "fill",
          source: "archives",
          paint: {
            "fill-color": ["get", "color"],
            "fill-opacity": 0.08,
          },
        });
        map.addLayer({
          id: "archives-line",
          type: "line",
          source: "archives",
          paint: {
            "line-color": ["get", "color"],
            "line-width": 1.5,
            "line-opacity": 0.5,
          },
        });

        // Circle centroid markers
        map.addSource("archives-points", {
          type: "geojson",
          data: { type: "FeatureCollection", features: pointFeatures },
        });
        map.addLayer({
          id: "archives-circles",
          type: "circle",
          source: "archives-points",
          paint: {
            "circle-radius": 8,
            "circle-color": ["get", "color"],
            "circle-stroke-color": "#ffffff",
            "circle-stroke-width": 2,
            "circle-opacity": 0.9,
          },
        });

        // Click handler → popup
        const clickHandler = (
          e: MapMouseEvent & { features?: MapGeoJSONFeature[] }
        ) => {
          if (!e.features?.length) return;
          const feat = e.features[0];
          const props = feat.properties as Record<string, unknown>;
          const geom = feat.geometry as { type: string; coordinates: number[] };
          if (geom.type !== "Point") return;

          const [lng, lat] = geom.coordinates;
          popupRef.current?.remove();
          popupRef.current = new Popup({ closeOnClick: true, maxWidth: "300px" })
            .setLngLat([lng, lat])
            .setHTML(renderArchivePopup(props))
            .addTo(map);
        };
        map.on("click", "archives-circles", clickHandler);
        archiveClickRef.current = clickHandler;

        // Cursor pointer on hover
        map.on("mouseenter", "archives-circles", () => {
          map.getCanvas().style.cursor = "pointer";
        });
        map.on("mouseleave", "archives-circles", () => {
          map.getCanvas().style.cursor = "";
        });
        break;
      }

      case "HIGHLIGHT_ARCHIVE": {
        // Change circle color: highlight target in yellow, keep others original
        if (map.getLayer("archives-circles")) {
          map.setPaintProperty("archives-circles", "circle-color", [
            "case",
            ["==", ["get", "archive_id"], action.archiveId],
            "#fbbf24",
            ["get", "color"],
          ] as Parameters<typeof map.setPaintProperty>[2]);
        }

        // Find stored coords and open popup
        const entry = archiveCoordsRef.current.get(action.archiveId);
        if (entry) {
          popupRef.current?.remove();
          popupRef.current = new Popup({ closeOnClick: true, maxWidth: "300px" })
            .setLngLat([entry.lng, entry.lat])
            .setHTML(renderArchivePopup(entry.props))
            .addTo(map);
          map.flyTo({ center: [entry.lng, entry.lat], zoom: 12, duration: 1200 });
        }
        break;
      }

      case "CLEAR_ARCHIVES": {
        if (archiveClickRef.current) {
          map.off("click", "archives-circles", archiveClickRef.current);
          archiveClickRef.current = null;
        }
        popupRef.current?.remove();
        popupRef.current = null;
        safeRemoveLayer(map, "archives-circles");
        safeRemoveLayer(map, "archives-line");
        safeRemoveLayer(map, "archives-fill");
        safeRemoveSource(map, "archives-points");
        safeRemoveSource(map, "archives");
        archiveCoordsRef.current.clear();
        break;
      }

      case "FLASH_AOI": {
        if (!map.getLayer("aoi-line")) break;
        // Flash AOI border 3 times to indicate order placement
        let tick = 0;
        const interval = setInterval(() => {
          if (map.getLayer("aoi-line")) {
            map.setPaintProperty(
              "aoi-line",
              "line-opacity",
              tick % 2 === 0 ? 0.1 : 1
            );
            map.setPaintProperty(
              "aoi-line",
              "line-width",
              tick % 2 === 0 ? 2 : 4
            );
          }
          tick++;
          if (tick >= 6) {
            clearInterval(interval);
            if (map.getLayer("aoi-line")) {
              map.setPaintProperty("aoi-line", "line-opacity", 1);
              map.setPaintProperty("aoi-line", "line-width", 2);
            }
          }
        }, 300);
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
