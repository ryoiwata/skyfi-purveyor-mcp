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
