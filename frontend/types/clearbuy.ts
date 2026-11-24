export type SpaceScope = "auto" | "nook" | "upgrade" | "full_room";

/** Normalized [y_min, x_min, y_max, x_max] on a 0–1000 coordinate grid */
export type NormalizedBBox = [number, number, number, number];

export interface AnchorDetection {
  id: string;
  label: string; // e.g., "US Outlet"
  known_size_label: string; // e.g., '4.5" H'
  px_per_in: number;
  bbox: NormalizedBBox;
  confidence: number;
}

export interface ProtectedAnchor {
  label: string;
  bbox: NormalizedBBox;
}

export interface DetectedZone {
  zone_id: string; // e.g., "Z1" or "zone_1"
  label: string; // e.g., "Zone 1 · Desk Wall"
  bbox: NormalizedBBox;
  width_in: number;
  depth_in: number;
  clearance_in?: number; // e.g., 24" pull-out or walkway
  protected_anchor?: boolean;
  user_overridden?: boolean;
}

export interface ScaleReadyEvent {
  session_id: string;
  detected_scope: SpaceScope;
  scope_label: string; // e.g., "Full Room · 2 Zones"
  calibration_layer: "layer1_anchor" | "layer2_depth_exif";
  tolerance_in: number; // 1.5 or 3.8
  exif_focal_mm?: number | null;
  fallback_badge?: string | null;
  anchors: AnchorDetection[];
  protected_anchors: ProtectedAnchor[];
  cross_anchor_skew_pct?: number;
  foreshortening_warning?: boolean;
  skew_warning?: string | null; // Triggered when multi-anchor disagreement > 15%
  zones: DetectedZone[];
  elapsed_ms: number;
}

export interface CatalogCandidate {
  sku_id: string;
  shopify_gid: string;
  title: string;
  merchant: string;
  price_usd: number;
  width_in?: number | null;
  depth_in?: number | null;
  height_in?: number | null;
  dimensions_unverified?: boolean;
  harmony_score?: number; // Decisions API score 0-3
  category_match?: boolean;
  image_url: string;
}

export interface CatalogReadyEvent {
  mcp_calls: string[];
  stores_scanned: number;
  skus_screened: number;
  catalog_gate_ms: number;
  candidates: CatalogCandidate[];
  elapsed_ms: number;
}

export type HookDecision = "DENY" | "RETRY" | "ALLOW";

export interface HookTraceEntry {
  id: string;
  decision: HookDecision;
  timestamp: string;
  tool_name: string;
  summary: string;
  detail?: string;
}

export interface HookEvent {
  status: "running" | "verified" | "self_corrected" | "refused";
  blocked_count: number;
  traces: HookTraceEntry[];
  refusal_reason?: string | null;
  elapsed_ms: number;
}

export interface ProductVariant {
  variant_id: string;
  label: string;
  color_hex: string;
  price_usd: number;
  in_stock: boolean;
}

export type FitBadgeState = "verified" | "unverified" | "blocked";

export interface VerifiedCartItem {
  item_id: string;
  pin_number: number; // 1, 2, 3...
  zone_id: string;
  sku_id: string;
  shopify_gid: string;
  title: string;
  category: string;
  merchant: string;
  price_usd: number;
  width_in?: number | null;
  depth_in?: number | null;
  height_in?: number | null;
  zone_width_in: number;
  fit_state: FitBadgeState;
  fit_label: string; // e.g., 'Verified Fit · 40.0" ≤ 43.5"'
  image_url: string;
  images?: string[];
  product_url?: string | null;
  merchant_sku?: string | null;
  stock_verified_at: number; // epoch ms
  selected_variant_id: string;
  variants: ProductVariant[];
  pin_position: { x: number; y: number }; // 0–1000 normalized canvas position
}

export interface MerchantCheckout {
  merchant: string;
  item_count: number;
  subtotal_usd: number;
  checkout_id: string;
  continue_url: string;
  ucp_payload: Record<string, unknown>;
}

export interface CartReadyEvent {
  status?: "verified" | "safe_refusal";
  refusal_reason?: string | null;
  items: VerifiedCartItem[];
  total_usd: number;
  budget_usd: number;
  checkouts: MerchantCheckout[];
  protocol_steps: string[];
  elapsed_ms: number;
}

export interface DecisionsQAResult {
  no_clipping: boolean;
  room_preserved: boolean;
  scale_honest: boolean;
  sku_fidelity: number; // 0–3
  confidence_band: "high_pass" | "borderline_amber" | "fail_repaired";
  latency_ms: number;
  output_tokens: number; // 0 for Decisions API
  repaired: boolean;
  repair_note?: string | null;
}

export interface RenderVersion {
  version_id: string; // "v1", "v2", ...
  label: string;
  image_url: string;
  decisions_qa: DecisionsQAResult;
  hotspot_pins?: {
    pin_number: number;
    sku_id: string;
    zone_id: string;
    x_norm: number;
    y_norm: number;
  }[];
  created_at: number;
}

export interface RenderReadyEvent {
  version: RenderVersion;
  elapsed_ms: number;
}

export interface AlternativeSKUCard {
  sku_id: string;
  shopify_gid: string;
  title: string;
  merchant: string;
  price_usd: number;
  price_delta_usd: number;
  width_in?: number | null;
  fit_delta_label: string;
  hook_blocked: boolean;
  block_reason?: string | null;
  image_url: string;
  zone_id: string;
  target_item_id: string;
}

export interface ThreadMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  pinned_chip?: string | null;
  alternatives?: AlternativeSKUCard[];
  timestamp: number;
}

export interface ThreadResponse {
  reply: string;
  alternatives: AlternativeSKUCard[];
  executed_swap?: SwapResponse | null;
}

export interface SwapResponse {
  allowed: boolean;
  hook_deny_reason?: string | null;
  updated_item?: VerifiedCartItem;
  updated_items?: VerifiedCartItem[];
  updated_checkouts?: MerchantCheckout[];
  updated_total_usd?: number;
  new_version?: RenderVersion;
}

export interface ZoneOverrideResponse {
  zone_id: string;
  width_in: number;
  depth_in: number;
  updated_items: VerifiedCartItem[];
  hook_traces: HookTraceEntry[];
}

export interface BenchmarkMethodRow {
  method: string;
  real_buyable_sku_pct: number;
  physical_fit_pass_pct: number;
  budget_compliance_pct: number;
  visual_qa_pass_pct: number;
  median_scale_err_in: string;
}

export interface AblationRow {
  model_config: string;
  multi_anchor_err_in: string;
  coupled_bundle_pass_pct: number;
  avg_latency_s: number;
}

export interface BenchmarkRoomSample {
  room_id: string;
  room_label: string;
  image_url?: string;
  kinect_gt_width_in: number;
  clearbuy_est_width_in: number;
  error_in: number;
  calibration_layer: "Layer 1 (Anchor)" | "Layer 2 (Depth+EXIF)";
  chosen_sku: string;
  blocked_sku?: string | null;
  status: "PASS" | "FALLBACK_PASS" | "FAILURE_FIXED";
  note: string;
}

export interface FailureAuditItem {
  id: string;
  title: string;
  room_ref: string;
  what_broke: string;
  how_we_fixed_it: string;
}

export interface BenchmarkData {
  rooms_tested: number;
  dataset_label: string;
  comparison_rows: BenchmarkMethodRow[];
  ablation_rows: AblationRow[];
  qa_catch_rate_pct: number;
  room_samples: BenchmarkRoomSample[];
  failure_audits: FailureAuditItem[];
}

export type StageStatus = "pending" | "active" | "verified" | "amber" | "blocked";

export interface DemoPreset {
  id: string;
  title: string;
  subtitle: string;
  scope: SpaceScope;
  budget_usd: number;
  prompt: string;
  room_image_url: string;
  rendered_image_url: string;
  rendered_v2_image_url: string;
  exif_focal_mm: number;
}
