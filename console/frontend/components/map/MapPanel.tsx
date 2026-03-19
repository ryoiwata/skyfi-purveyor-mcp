"use client";

import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef } from "react";
import { useMapContext } from "./MapContext";

/**
 * MapPanel — renders a full-height MapLibre GL map.
 *
 * Calls `registerMap` from MapContext once the map is fully loaded so that
 * dispatch actions can start modifying the map.
 */
export function MapPanel() {
  const containerRef = useRef<HTMLDivElement>(null);
  const { registerMap } = useMapContext();

  useEffect(() => {
    if (!containerRef.current) return;

    let map: import("maplibre-gl").Map | undefined;

    const init = async () => {
      const maplibregl = (await import("maplibre-gl")).default;

      map = new maplibregl.Map({
        container: containerRef.current!,
        style: "https://tiles.openfreemap.org/styles/liberty",
        center: [-98.5, 39.5],
        zoom: 4,
      });

      map.addControl(new maplibregl.NavigationControl(), "top-right");

      map.on("load", () => {
        registerMap(map!);
      });
    };

    init().catch((err) => console.error("MapPanel: init error", err));

    return () => {
      map?.remove();
    };
  }, [registerMap]);

  return <div ref={containerRef} className="w-full h-full" />;
}
