export type SseEvent =
  | { type: "text_delta"; token: string }
  | { type: "tool_call"; tool: string; input: Record<string, unknown> }
  | { type: "tool_result"; tool: string; output: unknown }
  | { type: "error"; message: string; code: string }
  | { type: "done" };

export interface BackendMessage {
  role: "user" | "assistant" | "tool";
  content: string;
}

// ---------------------------------------------------------------------------
// Archive types (from Purveyor search_archives tool output)
// ---------------------------------------------------------------------------

export interface ArchiveResult {
  archive_id: string;
  provider: string;
  constellation: string;
  product_type: string;
  resolution: string;
  capture_timestamp: string; // ISO datetime string
  cloud_coverage_percent: number | null;
  off_nadir_angle: number | null;
  footprint: string; // WKT POLYGON
  price_full_scene: number; // USD
  price_for_one_square_km: number;
  open_data: boolean;
  total_area_square_km: number;
  thumbnail_url?: string;
  skyfi_preview_url: string;
  overlap_ratio?: number;
  overlap_sqkm?: number;
}

export interface ArchiveSearchOutput {
  archives: ArchiveResult[];
  total: number;
  next_page?: string | null;
  aoi_area_km2?: number | null;
  summary: string;
}

// ---------------------------------------------------------------------------
// Order confirmation types (from create_archive_order / create_tasking_order)
// ---------------------------------------------------------------------------

export interface OrderConfirmationOutput {
  confirmation_url: string;
  confirmation_id: string;
  estimated_cost_cents: number;
  estimated_cost_dollars: string;
  aoi_area_km2: number;
  order_summary: string;
  // Archive-specific (present for create_archive_order)
  archive_id?: string;
  skyfi_preview_url?: string;
}

// ---------------------------------------------------------------------------
// Pricing types (from get_pricing)
// ---------------------------------------------------------------------------

export interface PricingOutput {
  pricing_matrix: Record<string, unknown>;
  aoi_area_sq_km: number | null;
  filters_applied: {
    product_type: string | null;
    resolution: string | null;
  };
  summary: string;
}

// ---------------------------------------------------------------------------
// Feasibility types (from check_feasibility)
// ---------------------------------------------------------------------------

export interface FeasibilityProviderScore {
  provider: string;
  score: number;
  status: string;
  opportunities: number;
}

export interface FeasibilityOutput {
  feasibility_id: string;
  status: "pending" | "complete";
  overall_score?: number;
  weather_score?: number | null;
  provider_scores?: FeasibilityProviderScore[];
  valid_until?: string;
  message?: string;
  summary: string;
}

// ---------------------------------------------------------------------------
// Pass prediction types (from get_pass_predictions)
// ---------------------------------------------------------------------------

export interface PassPredictionOutput {
  passes: Record<string, unknown>[];
  total: number;
  summary: string;
}
