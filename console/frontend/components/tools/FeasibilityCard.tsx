"use client";

import type { FeasibilityOutput } from "@/types/sse-events";

// ---------------------------------------------------------------------------
// Score gauge (simple horizontal bar)
// ---------------------------------------------------------------------------

function ScoreGauge({ score }: { score: number }) {
  const pct = Math.max(0, Math.min(1, score)) * 100;
  const color =
    score >= 0.75
      ? "bg-green-500"
      : score >= 0.5
        ? "bg-yellow-500"
        : "bg-red-500";

  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 bg-gray-200 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs font-mono text-gray-700 w-10 text-right">
        {(score * 100).toFixed(0)}%
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Rating label
// ---------------------------------------------------------------------------

function ratingLabel(score: number): { label: string; color: string } {
  if (score >= 0.75) return { label: "HIGH", color: "text-green-700" };
  if (score >= 0.5) return { label: "MEDIUM", color: "text-yellow-700" };
  return { label: "LOW", color: "text-red-700" };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface FeasibilityCardProps {
  output: FeasibilityOutput;
}

export function FeasibilityCard({ output }: FeasibilityCardProps) {
  // ---- Pending state ----
  if (output.status === "pending") {
    return (
      <div className="border border-gray-200 rounded-lg bg-gray-50 p-3 text-xs">
        <div className="flex items-center gap-2 text-gray-600">
          <span className="animate-spin text-base">⟳</span>
          <div>
            <div className="font-medium text-gray-700">Feasibility check in progress…</div>
            <div className="text-gray-500 text-[10px] mt-0.5 font-mono">
              ID: {output.feasibility_id}
            </div>
          </div>
        </div>
        {output.message && (
          <p className="mt-2 text-gray-500 text-[10px] leading-relaxed">{output.message}</p>
        )}
      </div>
    );
  }

  // ---- Complete state ----
  const score = output.overall_score ?? 0;
  const { label, color } = ratingLabel(score);

  return (
    <div className="border border-gray-200 rounded-lg bg-white overflow-hidden text-xs">
      {/* Header */}
      <div className="px-3 py-2.5 border-b border-gray-100 bg-gray-50 flex items-center justify-between">
        <span className="font-semibold text-gray-700">Feasibility Assessment</span>
        <span className={`font-bold text-sm ${color}`}>{label}</span>
      </div>

      <div className="px-3 py-3 space-y-3">
        {/* Overall score gauge */}
        <div>
          <div className="text-[10px] text-gray-500 uppercase tracking-wide mb-1 font-medium">
            Overall Score
          </div>
          <ScoreGauge score={score} />
        </div>

        {/* Weather score */}
        {output.weather_score != null && (
          <div>
            <div className="text-[10px] text-gray-500 uppercase tracking-wide mb-1 font-medium">
              Weather Score
            </div>
            <ScoreGauge score={output.weather_score} />
          </div>
        )}

        {/* Provider scores */}
        {output.provider_scores && output.provider_scores.length > 0 && (
          <div>
            <div className="text-[10px] text-gray-500 uppercase tracking-wide mb-1.5 font-medium">
              Providers Evaluated
            </div>
            <div className="space-y-1.5">
              {output.provider_scores.map((ps) => (
                <div key={ps.provider} className="flex items-center justify-between">
                  <span className="text-gray-600 font-medium w-20 shrink-0">{ps.provider}</span>
                  <div className="flex-1 mx-2">
                    <ScoreGauge score={ps.score} />
                  </div>
                  <span className="text-[10px] text-gray-500 shrink-0 w-16 text-right">
                    {ps.opportunities} pass{ps.opportunities !== 1 ? "es" : ""}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Valid until */}
        {output.valid_until && (
          <div className="text-[10px] text-gray-400 border-t border-gray-100 pt-2">
            Valid until:{" "}
            {new Date(output.valid_until).toLocaleString("en-US", {
              month: "short",
              day: "numeric",
              hour: "numeric",
              minute: "2-digit",
              timeZoneName: "short",
            })}
          </div>
        )}

        {/* Feasibility ID */}
        <div className="text-[10px] text-gray-400 font-mono">
          ID: {output.feasibility_id}
        </div>
      </div>
    </div>
  );
}
