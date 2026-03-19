"use client";

import type { PricingOutput } from "@/types/sse-events";

// ---------------------------------------------------------------------------
// Helpers to parse the opaque SkyFi pricing matrix
// ---------------------------------------------------------------------------

interface PricingRow {
  key: string;
  label: string;
  pricePerSqKm: number;
  resolution: string;
  provider: string;
  productType: string;
}

const RESOLUTION_ORDER = ["VERY HIGH", "HIGH", "MEDIUM", "LOW", ""];

function normLabel(raw: string): string {
  // Convert snake/camel/uppercase key fragments into readable labels
  return raw
    .replace(/_/g, " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function extractResolution(key: string): string {
  const upper = key.toUpperCase();
  if (upper.includes("VERY_HIGH") || upper.includes("VERY HIGH")) return "VERY HIGH";
  if (upper.includes("HIGH")) return "HIGH";
  if (upper.includes("MEDIUM") || upper.includes("MED")) return "MEDIUM";
  if (upper.includes("LOW")) return "LOW";
  return "";
}

function extractProvider(key: string): string {
  const known = ["PLANET", "MAXAR", "AIRBUS", "SATELLOGIC", "UMBRA", "SENTINEL", "LANDSAT", "SPIRE"];
  const upper = key.toUpperCase();
  for (const p of known) {
    if (upper.includes(p)) return p;
  }
  return "";
}

function extractProductType(key: string): string {
  const upper = key.toUpperCase();
  if (upper.includes("SAR")) return "SAR";
  if (upper.includes("DAY")) return "DAY";
  if (upper.includes("NIGHT")) return "NIGHT";
  if (upper.includes("VIDEO")) return "VIDEO";
  return "";
}

/**
 * Flatten the pricing matrix into rows.
 * The SkyFi pricing matrix can be:
 *   { "key": number }                       — price per sq km
 *   { "key": { "subkey": number, ... } }    — nested pricing
 */
function flattenPricingMatrix(matrix: Record<string, unknown>): PricingRow[] {
  const rows: PricingRow[] = [];

  for (const [key, value] of Object.entries(matrix)) {
    if (typeof value === "number") {
      rows.push({
        key,
        label: normLabel(key),
        pricePerSqKm: value,
        resolution: extractResolution(key),
        provider: extractProvider(key),
        productType: extractProductType(key),
      });
    } else if (value !== null && typeof value === "object") {
      // Nested: iterate sub-keys
      for (const [subKey, subValue] of Object.entries(value as Record<string, unknown>)) {
        if (typeof subValue === "number") {
          const combinedKey = `${key}__${subKey}`;
          rows.push({
            key: combinedKey,
            label: `${normLabel(key)} / ${normLabel(subKey)}`,
            pricePerSqKm: subValue,
            resolution: extractResolution(`${key} ${subKey}`),
            provider: extractProvider(`${key} ${subKey}`),
            productType: extractProductType(`${key} ${subKey}`),
          });
        }
      }
    }
  }

  // Sort: by resolution tier order, then by price
  rows.sort((a, b) => {
    const ri = RESOLUTION_ORDER.indexOf(a.resolution);
    const rj = RESOLUTION_ORDER.indexOf(b.resolution);
    if (ri !== rj) return ri - rj;
    return a.pricePerSqKm - b.pricePerSqKm;
  });

  return rows;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface PricingTableProps {
  output: PricingOutput;
}

export function PricingTable({ output }: PricingTableProps) {
  const rows = flattenPricingMatrix(output.pricing_matrix);

  if (rows.length === 0) {
    return (
      <div className="text-xs text-gray-500 py-2">
        No pricing data available.
      </div>
    );
  }

  // Find min price per resolution tier for green highlighting
  const minPriceByResolution: Record<string, number> = {};
  for (const row of rows) {
    const tier = row.resolution || "OTHER";
    if (!(tier in minPriceByResolution) || row.pricePerSqKm < minPriceByResolution[tier]) {
      minPriceByResolution[tier] = row.pricePerSqKm;
    }
  }

  return (
    <div className="text-xs overflow-hidden rounded-lg border border-gray-200">
      {/* Summary */}
      {output.summary && (
        <div className="px-3 py-2 bg-gray-50 border-b border-gray-200 text-gray-600 text-[11px]">
          {output.summary}
        </div>
      )}

      {/* AOI cost estimate */}
      {output.aoi_area_sq_km != null && (
        <div className="px-3 py-1.5 bg-blue-50 border-b border-blue-100 text-blue-700 text-[11px]">
          AOI area: {output.aoi_area_sq_km.toFixed(1)} km²
        </div>
      )}

      {/* Table */}
      <table className="w-full text-[11px]">
        <thead>
          <tr className="bg-gray-50 border-b border-gray-200">
            <th className="text-left px-3 py-2 font-medium text-gray-600">Resolution</th>
            <th className="text-left px-3 py-2 font-medium text-gray-600">Provider</th>
            <th className="text-right px-3 py-2 font-medium text-gray-600">$/km²</th>
            {output.aoi_area_sq_km != null && (
              <th className="text-right px-3 py-2 font-medium text-gray-600">Est. Total</th>
            )}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const tier = row.resolution || "OTHER";
            const isCheapest = row.pricePerSqKm === minPriceByResolution[tier];
            const estTotal =
              output.aoi_area_sq_km != null
                ? row.pricePerSqKm * output.aoi_area_sq_km
                : null;

            return (
              <tr
                key={row.key}
                className={`border-b border-gray-100 last:border-0 ${
                  isCheapest ? "bg-green-50" : "hover:bg-gray-50"
                }`}
              >
                <td className="px-3 py-2 text-gray-700">
                  {row.resolution || (row.productType || row.label.split("/")[0].trim())}
                  {isCheapest && (
                    <span className="ml-1 text-[9px] text-green-600 font-semibold uppercase tracking-wide">
                      best
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-gray-600">
                  {row.provider || row.label.split("/").pop()?.trim() || "—"}
                </td>
                <td className="px-3 py-2 text-right font-mono text-gray-800">
                  ${row.pricePerSqKm.toFixed(4)}
                </td>
                {estTotal != null && (
                  <td className="px-3 py-2 text-right font-semibold text-gray-800">
                    ${estTotal.toFixed(0)}
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
