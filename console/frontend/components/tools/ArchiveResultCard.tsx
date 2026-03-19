"use client";

import { useState } from "react";
import type { ArchiveResult } from "@/types/sse-events";

export const PROVIDER_COLORS: Record<string, string> = {
  PLANET: "#10b981",
  MAXAR: "#3b82f6",
  AIRBUS: "#8b5cf6",
  SATELLOGIC: "#f59e0b",
  UMBRA: "#ef4444",
  SENTINEL2: "#06b6d4",
  LANDSAT: "#84cc16",
  SPIRE: "#f97316",
};

interface ArchiveResultCardProps {
  archive: ArchiveResult;
  onHighlight?: (archiveId: string) => void;
}

export function ArchiveResultCard({ archive, onHighlight }: ArchiveResultCardProps) {
  const [imgError, setImgError] = useState(false);

  const providerColor = PROVIDER_COLORS[archive.provider] ?? "#6b7280";
  const captureDate = archive.capture_timestamp
    ? new Date(archive.capture_timestamp).toLocaleDateString("en-US", {
        year: "numeric",
        month: "short",
        day: "numeric",
      })
    : "Unknown";

  const cloud = archive.cloud_coverage_percent;
  const cloudColor =
    cloud === null
      ? "text-gray-400"
      : cloud < 10
        ? "text-green-600"
        : cloud < 30
          ? "text-yellow-600"
          : "text-red-600";

  const priceLabel = archive.open_data
    ? "Free (open data)"
    : `$${archive.price_full_scene.toFixed(0)}`;

  const hasThumbnail = !!archive.thumbnail_url && !imgError;

  return (
    <div
      className="border border-gray-200 rounded-lg p-3 bg-white hover:bg-gray-50 transition-colors text-xs"
      onMouseEnter={() => onHighlight?.(archive.archive_id)}
    >
      <div className="flex items-start gap-2.5">
        {/* Thumbnail */}
        <div className="shrink-0 w-16 h-16 rounded overflow-hidden bg-gray-100 flex items-center justify-center border border-gray-200">
          {hasThumbnail ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={archive.thumbnail_url}
              alt={`${archive.provider} archive thumbnail`}
              className="w-full h-full object-cover"
              onError={() => setImgError(true)}
              loading="lazy"
            />
          ) : (
            <span className="text-gray-400 text-[10px] text-center px-1">No preview</span>
          )}
        </div>

        {/* Metadata */}
        <div className="flex-1 min-w-0">
          {/* Provider + resolution badges */}
          <div className="flex items-center gap-1 mb-1.5 flex-wrap">
            <span
              className="px-1.5 py-0.5 rounded text-white font-semibold"
              style={{ backgroundColor: providerColor, fontSize: "10px" }}
            >
              {archive.provider}
            </span>
            <span className="px-1.5 py-0.5 rounded bg-slate-100 text-slate-700 font-medium text-[10px]">
              {archive.resolution}
            </span>
            {archive.open_data && (
              <span className="px-1.5 py-0.5 rounded bg-green-100 text-green-700 font-medium text-[10px]">
                FREE
              </span>
            )}
          </div>

          {/* Details */}
          <div className="space-y-0.5 text-gray-600">
            <div>📅 {captureDate}</div>
            {cloud !== null && (
              <div className={cloudColor}>
                ☁ {cloud.toFixed(0)}% cloud cover
              </div>
            )}
            <div className="font-semibold text-gray-800 text-sm mt-1">{priceLabel}</div>
          </div>
        </div>
      </div>

      {/* Footer */}
      <div className="mt-2 pt-1.5 border-t border-gray-100 flex justify-end">
        <a
          href={archive.skyfi_preview_url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-blue-600 hover:text-blue-800 underline text-[11px]"
          onClick={(e) => e.stopPropagation()}
        >
          View on SkyFi →
        </a>
      </div>
    </div>
  );
}
