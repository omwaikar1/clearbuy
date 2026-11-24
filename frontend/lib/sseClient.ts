import type {
  AlternativeSKUCard,
  BenchmarkData,
  CartReadyEvent,
  CatalogReadyEvent,
  DecisionsQAResult,
  HookEvent,
  HookTraceEntry,
  MerchantCheckout,
  NormalizedBBox,
  RenderReadyEvent,
  ScaleReadyEvent,
  SpaceScope,
  SwapResponse,
  ThreadResponse,
  VerifiedCartItem,
  ZoneOverrideResponse,
} from "@/types/clearbuy";
import {
  buildMockPipelinePayloads,
  DEMO_PRESETS,
  MOCK_ADVERSARIAL_DESK_ALTERNATIVES,
  MOCK_BENCHMARK_DATA,
  MOCK_CHAIR_ALTERNATIVES,
} from "./mockData";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

export const DEFAULT_USE_MOCK =
  process.env.NEXT_PUBLIC_USE_MOCK_SSE === "true";

export interface SessionStreamCallbacks {
  onSessionCreated?: (sessionId: string) => void;
  onScaleReady: (data: ScaleReadyEvent) => void;
  onCatalogReady: (data: CatalogReadyEvent) => void;
  onHookEvent: (data: HookEvent) => void;
  onCartReady: (data: CartReadyEvent) => void;
  onRenderReady: (data: RenderReadyEvent) => void;
  onError: (message: string) => void;
}

export interface StartSessionParams {
  images: File[];
  exifFocalMm: number | null;
  prompt: string;
  budgetUsd: number;
  scope: SpaceScope;
  useMock: boolean;
  mockPresetId?: string | null;
  fallbackPreviewUrl?: string;
}

/* -------------------------------------------------------------------------- */
/* Backend Schema Normalizers (bridges backend/schemas.py -> frontend types)  */
/* -------------------------------------------------------------------------- */

function normalizeBBox(raw: unknown): NormalizedBBox {
  if (Array.isArray(raw) && raw.length >= 4) {
    return [Number(raw[0]), Number(raw[1]), Number(raw[2]), Number(raw[3])];
  }
  if (raw && typeof raw === "object") {
    const b = raw as Record<string, unknown>;
    return [
      Number(b.y_min ?? 0),
      Number(b.x_min ?? 0),
      Number(b.y_max ?? 1000),
      Number(b.x_max ?? 1000),
    ];
  }
  return [200, 200, 800, 800];
}

function guessColorHex(label: string): string {
  const lower = label.toLowerCase();
  if (lower.includes("walnut") || lower.includes("espresso")) return "#6B4423";
  if (lower.includes("oak") || lower.includes("maple") || lower.includes("natural"))
    return "#C99A6B";
  if (lower.includes("black") || lower.includes("charcoal")) return "#27272A";
  if (lower.includes("white") || lower.includes("ivory")) return "#F4F4F5";
  if (lower.includes("cream") || lower.includes("oat") || lower.includes("linen"))
    return "#E8D5C4";
  if (lower.includes("brass") || lower.includes("gold")) return "#D4AF37";
  if (lower.includes("sage") || lower.includes("green")) return "#6B8E78";
  if (lower.includes("blue") || lower.includes("navy")) return "#3B82F6";
  return "#64748B";
}

function normalizeScopeLabel(scope: SpaceScope, zoneCount: number): string {
  const prefix =
    scope === "full_room"
      ? "Full Room"
      : scope === "upgrade"
      ? "Setup Upgrade"
      : "Single Nook";
  return `${prefix} · ${zoneCount} Zone${zoneCount === 1 ? "" : "s"}`;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function normalizeScaleReady(raw: any): ScaleReadyEvent {
  const zonesRaw = Array.isArray(raw.zones) ? raw.zones : [];
  const anchorsRaw = Array.isArray(raw.anchors_detected)
    ? raw.anchors_detected
    : Array.isArray(raw.anchors)
    ? raw.anchors
    : raw.primary_anchor
    ? [raw.primary_anchor]
    : [];

  const protectedRaw = Array.isArray(raw.protected_anchors)
    ? raw.protected_anchors
    : [];

  const layer: "layer1_anchor" | "layer2_depth_exif" =
    raw.calibration_layer === 2 || raw.calibration_layer === "layer2_depth_exif"
      ? "layer2_depth_exif"
      : "layer1_anchor";

  const skewPct = Number(raw.cross_anchor_skew_pct ?? 0);
  const foreshortening = Boolean(raw.foreshortening_warning) || skewPct > 15;
  const skewWarning =
    raw.skew_warning ??
    (foreshortening
      ? `Perspective skew detected (${skewPct.toFixed(0)}% anchor disagreement)`
      : null);

  const detectedScope: SpaceScope = raw.detected_scope ?? "nook";

  return {
    session_id: String(raw.session_id ?? ""),
    detected_scope: detectedScope,
    scope_label:
      raw.scope_label || normalizeScopeLabel(detectedScope, zonesRaw.length || 1),
    calibration_layer: layer,
    tolerance_in: Number(
      raw.tolerance_in ??
        zonesRaw[0]?.tolerance_in ??
        (layer === "layer2_depth_exif" ? 3.8 : 1.5)
    ),
    exif_focal_mm: raw.exif_focal_mm ?? null,
    fallback_badge: raw.fallback_badge ?? null,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    anchors: anchorsRaw.map((a: any, idx: number) => ({
      id: String(a.anchor_id ?? a.id ?? `anchor-${idx}`),
      label: String(a.label ?? "Room Anchor"),
      known_size_label:
        a.known_size_label ??
        (a.known_inches
          ? `${a.known_inches}" ${a.measured_axis === "width" ? "W" : "H"}`
          : '4.5" H'),
      px_per_in: Number(a.px_per_in ?? 14.0),
      bbox: normalizeBBox(a.bbox),
      confidence: Number(a.confidence ?? 0.95),
    })),
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    protected_anchors: protectedRaw.map((p: any) => ({
      label: String(p.label ?? "Protected Item"),
      bbox: normalizeBBox(p.bbox),
    })),
    cross_anchor_skew_pct: skewPct,
    foreshortening_warning: foreshortening,
    skew_warning: skewWarning,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    zones: zonesRaw.map((z: any, idx: number) => ({
      zone_id: String(z.zone_id ?? `Z${idx + 1}`),
      label: String(z.label ?? `Zone ${idx + 1}`),
      bbox: normalizeBBox(z.bbox),
      width_in: Number(z.width_in ?? 43.5),
      depth_in: Number(z.depth_in ?? 30.0),
      clearance_in: Number(z.clearance_required_in ?? z.clearance_in ?? 24),
      protected_anchor: Boolean(z.protected_anchor),
      user_overridden: Boolean(z.overridden_by_user ?? z.user_overridden),
    })),
    elapsed_ms: Number(raw.elapsed_ms ?? 0),
  };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function normalizeCatalogReady(raw: any): CatalogReadyEvent {
  const mcpCalls: string[] = Array.isArray(raw.queries_executed)
    ? raw.queries_executed.map((q: string) => `search_catalog("${q}")`)
    : Array.isArray(raw.mcp_calls)
    ? // eslint-disable-next-line @typescript-eslint/no-explicit-any
      raw.mcp_calls.map((c: any) =>
        typeof c === "string"
          ? c
          : `${c.tool_name}(${JSON.stringify(c.arguments ?? {}).slice(0, 60)})`
      )
    : [];

  const flatCandidates: CatalogReadyEvent["candidates"] = [];
  if (raw.candidates_by_category && typeof raw.candidates_by_category === "object") {
    Object.values(raw.candidates_by_category).forEach((list) => {
      if (Array.isArray(list)) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        list.forEach((s: any) => {
          flatCandidates.push({
            sku_id: String(s.sku_id ?? ""),
            shopify_gid: String(s.gid ?? s.shopify_gid ?? ""),
            title: String(s.title ?? ""),
            merchant: String(s.merchant_name ?? s.merchant ?? "Shopify Store"),
            price_usd: Number(s.price_usd ?? 0),
            width_in: s.dimensions?.width_in ?? s.width_in ?? null,
            depth_in: s.dimensions?.depth_in ?? s.depth_in ?? null,
            height_in: s.dimensions?.height_in ?? s.height_in ?? null,
            dimensions_unverified: Boolean(
              s.dimensions?.dimensions_unverified ?? s.dimensions_unverified
            ),
            harmony_score: s.decisions_gate?.harmony_score ?? s.harmony_score,
            category_match: (s.decisions_gate?.category_match_prob ?? 1) >= 0.5,
            image_url: String(s.image_url ?? ""),
          });
        });
      }
    });
  } else if (Array.isArray(raw.candidates)) {
    flatCandidates.push(...raw.candidates);
  }

  return {
    mcp_calls: mcpCalls,
    stores_scanned: Number(raw.stores_scanned ?? 0),
    skus_screened: Number(raw.candidates_count ?? raw.skus_screened ?? flatCandidates.length),
    catalog_gate_ms: Number(raw.decisions_gate_latency_ms ?? raw.catalog_gate_ms ?? 190),
    candidates: flatCandidates,
    elapsed_ms: Number(raw.elapsed_ms ?? 0),
  };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function normalizeHookEvent(raw: any, prevTraces: HookTraceEntry[] = []): HookEvent {
  if (Array.isArray(raw.traces)) {
    return raw as HookEvent;
  }

  const decisionUpper =
    String(raw.decision ?? "allow").toUpperCase() === "DENY" ? "DENY" : "ALLOW";
  const attempt = Number(raw.attempt ?? prevTraces.length + 1);
  const violationSummary =
    Array.isArray(raw.violations) && raw.violations.length > 0
      ? // eslint-disable-next-line @typescript-eslint/no-explicit-any
        raw.violations.map((v: any) => v.message).join("; ")
      : String(raw.reason ?? "");

  const nextEntry: HookTraceEntry = {
    id: `hook-${attempt}-${Date.now()}`,
    decision: decisionUpper,
    timestamp: `attempt #${attempt}`,
    tool_name: "write_to_file(/workspace/cart_proposal.json)",
    summary:
      decisionUpper === "DENY"
        ? `DENY ${violationSummary}`
        : `ALLOW ${raw.reason || "Bundle verified within wall clearance & budget"}`,
    detail: raw.remediation_hint ?? undefined,
  };

  const traces = [...prevTraces, nextEntry];
  const blockedCount = traces.filter((t) => t.decision === "DENY").length;
  const status: HookEvent["status"] =
    decisionUpper === "DENY"
      ? "running"
      : blockedCount > 0
      ? "self_corrected"
      : "verified";

  return {
    status,
    blocked_count: blockedCount,
    traces,
    refusal_reason: raw.refusal_reason ?? null,
    elapsed_ms: Number(raw.elapsed_ms ?? 0),
  };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function normalizeShopifySKU(s: any, idx: number, zoneWidthIn = 43.5): VerifiedCartItem {
  const fitRaw = String(s.fit_status ?? s.fit_state ?? "verified_fit");
  const fitState: VerifiedCartItem["fit_state"] =
    fitRaw === "blocked_by_hook" || fitRaw === "blocked"
      ? "blocked"
      : fitRaw === "unverified_specs" ||
        fitRaw === "unverified" ||
        s.dimensions?.dimensions_unverified
      ? "unverified"
      : "verified";

  const widthIn = s.dimensions?.width_in ?? s.width_in ?? null;
  const depthIn = s.dimensions?.depth_in ?? s.depth_in ?? null;
  const heightIn = s.dimensions?.height_in ?? s.height_in ?? null;

  const verifiedEpoch =
    typeof s.stock_verified_at === "number"
      ? s.stock_verified_at
      : s.verified_at
      ? Date.parse(s.verified_at) || Date.now()
      : Date.now();

  const variantsRaw = Array.isArray(s.variants) ? s.variants : [];
  const variants = variantsRaw.map(
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (v: any) => ({
      variant_id: String(v.variant_id ?? v.gid ?? ""),
      label: String(v.title ?? v.label ?? "Default"),
      color_hex: v.color_hex || guessColorHex(String(v.title ?? v.label ?? "")),
      price_usd: Number(v.price_usd ?? s.price_usd ?? 0),
      in_stock: Boolean(v.available ?? v.in_stock ?? true),
    })
  );

  const defaultPinX = 320 + (idx % 3) * 140;
  const defaultPinY = 500 + (idx % 2) * 90;

  return {
    item_id: String(s.item_id ?? s.sku_id ?? `item-${idx + 1}`),
    pin_number: Number(s.pin_number ?? idx + 1),
    zone_id: String(s.zone_id ?? "Z1"),
    sku_id: String(s.sku_id ?? ""),
    shopify_gid: String(s.gid ?? s.shopify_gid ?? ""),
    title: String(s.title ?? "Shopify Product"),
    category: String(s.category ?? "Furniture"),
    merchant: String(s.merchant_name ?? s.merchant ?? "Shopify Store"),
    price_usd: Number(s.price_usd ?? 0),
    width_in: widthIn !== null ? Number(widthIn) : null,
    depth_in: depthIn !== null ? Number(depthIn) : null,
    height_in: heightIn !== null ? Number(heightIn) : null,
    zone_width_in: Number(s.zone_width_in ?? zoneWidthIn),
    fit_state: fitState,
    fit_label:
      s.fit_badge_text ||
      s.fit_label ||
      (fitState === "verified" && widthIn
        ? `Verified Fit · ${Number(widthIn).toFixed(1)}" ≤ ${zoneWidthIn.toFixed(1)}"`
        : fitState === "unverified"
        ? "Unverified Specs · Check Seller"
        : "Blocked by Hook"),
    image_url: String(s.image_url ?? ""),
    images: Array.isArray(s.images) && s.images.length > 0
      ? s.images.map((u: unknown) => String(u)).filter(Boolean)
      : s.image_url
      ? [String(s.image_url)]
      : [],
    product_url: s.product_url ? String(s.product_url) : null,
    merchant_sku: s.merchant_sku ? String(s.merchant_sku) : null,
    stock_verified_at: verifiedEpoch,
    selected_variant_id: String(
      s.selected_variant_id ?? variants[0]?.variant_id ?? ""
    ),
    variants,
    pin_position: s.pin_position ?? { x: defaultPinX, y: defaultPinY },
  };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function normalizeCheckouts(rawCheckouts: any[]): MerchantCheckout[] {
  return (rawCheckouts || []).map((c) => ({
    merchant: String(c.merchant_name ?? c.merchant ?? "Shopify Store"),
    item_count: Number(c.item_count ?? 1),
    subtotal_usd: Number(c.total_usd || c.subtotal_usd || 0),
    checkout_id: String(c.checkout_id ?? ""),
    continue_url: String(c.continue_url ?? "#"),
    ucp_payload: c.raw_ucp_payload ?? c.ucp_payload ?? c,
  }));
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function normalizeCartReady(raw: any): CartReadyEvent {
  const itemsRaw = Array.isArray(raw.verified_items)
    ? raw.verified_items
    : Array.isArray(raw.items)
    ? raw.items
    : [];

  return {
    status: raw.status === "safe_refusal" ? "safe_refusal" : "verified",
    refusal_reason: raw.refusal_reason ?? null,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    items: itemsRaw.map((s: any, idx: number) => normalizeShopifySKU(s, idx)),
    total_usd: Number(raw.total_usd ?? 0),
    budget_usd: Number(raw.budget_usd ?? 450),
    checkouts: normalizeCheckouts(raw.checkouts ?? []),
    protocol_steps: raw.protocol_steps ?? [
      "search_catalog",
      "get_product",
      "create_checkout",
    ],
    elapsed_ms: Number(raw.elapsed_ms ?? 0),
  };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function normalizeDecisionsQA(raw: any, repaired = false, repairNote?: string | null): DecisionsQAResult {
  const statusStr = String(raw?.status ?? "verified");
  const confidenceBand: DecisionsQAResult["confidence_band"] =
    raw?.confidence_band ??
    (statusStr === "borderline"
      ? "borderline_amber"
      : statusStr === "repaired" || statusStr === "failed" || repaired
      ? "fail_repaired"
      : "high_pass");

  return {
    no_clipping: Boolean(raw?.no_clipping ?? true),
    room_preserved: Boolean(raw?.room_preserved ?? true),
    scale_honest: Boolean(raw?.scale_honest ?? true),
    sku_fidelity: Number(raw?.sku_fidelity ?? 3),
    confidence_band: confidenceBand,
    latency_ms: Number(raw?.latency_ms ?? 184),
    output_tokens: Number(raw?.output_tokens ?? 0),
    repaired: Boolean(raw?.repaired ?? repaired),
    repair_note: raw?.defect_summary ?? raw?.repair_note ?? repairNote ?? null,
  };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function normalizeRenderReady(raw: any): RenderReadyEvent {
  if (raw.version && raw.version.image_url) {
    return raw as RenderReadyEvent;
  }

  const mime = raw.image_mime || "image/jpeg";
  const imageUrl = raw.image_url
    ? String(raw.image_url)
    : raw.image_b64
    ? raw.image_b64.startsWith("data:")
      ? raw.image_b64
      : `data:${mime};base64,${raw.image_b64}`
    : "";

  return {
    version: {
      version_id: String(raw.version_id ?? "v1"),
      label: raw.repaired ? "Auto-Repaired Verified Render" : "Verified Studio Render",
      image_url: imageUrl,
      decisions_qa: normalizeDecisionsQA(
        raw.decisions_qa,
        Boolean(raw.repaired),
        raw.repair_reason
      ),
      hotspot_pins: Array.isArray(raw.hotspot_pins) ? raw.hotspot_pins : undefined,
      created_at: Date.now(),
    },
    elapsed_ms: Number(raw.elapsed_ms ?? 0),
  };
}

/* -------------------------------------------------------------------------- */
/* SSE & REST API Client                                                      */
/* -------------------------------------------------------------------------- */

export async function startSessionStream(
  params: StartSessionParams,
  callbacks: SessionStreamCallbacks,
  signal?: AbortSignal
): Promise<void> {
  if (params.useMock) {
    return runMockSessionStream(params, callbacks, signal);
  }

  try {
    const formData = new FormData();
    params.images.forEach((img) => formData.append("images", img));
    if (params.exifFocalMm !== null) {
      formData.append("exif_focal_mm", String(params.exifFocalMm));
    }
    formData.append("prompt", params.prompt);
    formData.append("budget_usd", String(params.budgetUsd));
    formData.append("scope", params.scope);

    const response = await fetch(`${API_BASE_URL}/api/session/start`, {
      method: "POST",
      body: formData,
      signal,
    });

    if (!response.ok || !response.body) {
      throw new Error(`Session start failed (${response.status})`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let accumulatedHookTraces: HookTraceEntry[] = [];

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const chunks = buffer.split("\n\n");
      buffer = chunks.pop() ?? "";

      for (const chunk of chunks) {
        const lines = chunk.split("\n");
        let eventName = "message";
        const dataLines: string[] = [];

        for (const line of lines) {
          if (line.startsWith("event:")) {
            eventName = line.slice(6).trim();
          } else if (line.startsWith("data:")) {
            dataLines.push(line.slice(5).trim());
          }
        }

        if (dataLines.length === 0) continue;
        const parsed = JSON.parse(dataLines.join("\n"));

        switch (eventName) {
          case "session_created":
            callbacks.onSessionCreated?.(parsed.session_id);
            break;
          case "scale_ready": {
            const norm = normalizeScaleReady(parsed);
            if (norm.session_id) callbacks.onSessionCreated?.(norm.session_id);
            callbacks.onScaleReady(norm);
            break;
          }
          case "catalog_ready":
            callbacks.onCatalogReady(normalizeCatalogReady(parsed));
            break;
          case "hook_event": {
            const norm = normalizeHookEvent(parsed, accumulatedHookTraces);
            accumulatedHookTraces = norm.traces;
            callbacks.onHookEvent(norm);
            break;
          }
          case "cart_ready":
            callbacks.onCartReady(normalizeCartReady(parsed));
            break;
          case "render_ready":
            callbacks.onRenderReady(normalizeRenderReady(parsed));
            break;
          case "error":
            callbacks.onError(parsed.message || parsed.detail || "Pipeline error");
            break;
        }
      }
    }
  } catch (err) {
    if ((err as Error).name === "AbortError") return;
    callbacks.onError((err as Error).message || "Unable to connect to FastAPI SSE stream");
  }
}

async function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const id = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => {
      clearTimeout(id);
      reject(new DOMException("Aborted", "AbortError"));
    });
  });
}

async function runMockSessionStream(
  params: StartSessionParams,
  callbacks: SessionStreamCallbacks,
  signal?: AbortSignal
): Promise<void> {
  try {
    const sessionId = `mock_${Date.now().toString(36)}`;
    callbacks.onSessionCreated?.(sessionId);

    const preset =
      DEMO_PRESETS.find((p) => p.id === params.mockPresetId) || DEMO_PRESETS[0];
    const payloads = buildMockPipelinePayloads({
      sessionId,
      scope: params.scope === "auto" ? preset.scope : params.scope,
      budgetUsd: params.budgetUsd,
      exifFocalMm: params.exifFocalMm ?? preset.exif_focal_mm,
      renderedImageUrl: preset.rendered_image_url,
    });

    await sleep(900, signal);
    callbacks.onScaleReady(payloads.scale);

    await sleep(750, signal);
    callbacks.onCatalogReady(payloads.catalog);

    await sleep(750, signal);
    callbacks.onHookEvent(payloads.hook);

    await sleep(600, signal);
    callbacks.onCartReady(payloads.cart);

    await sleep(1100, signal);
    callbacks.onRenderReady(payloads.render);
  } catch (err) {
    if ((err as Error).name === "AbortError") return;
    callbacks.onError((err as Error).message);
  }
}

export async function sendThreadUtterance(params: {
  sessionId: string;
  utterance: string;
  pinnedZoneId?: string | null;
  pinnedItemId?: string | null;
  useMock: boolean;
}): Promise<ThreadResponse> {
  if (params.useMock) {
    await sleep(550);
    const lower = params.utterance.toLowerCase();
    const isAdversarial =
      lower.includes("72") || lower.includes("executive") || lower.includes("huge");

    if (isAdversarial) {
      return {
        reply:
          'hooks.json blocked the 72" Executive Desk (+28.5" over your 43.5" Zone 1 wall). Here are verified walnut/oak desks that physically fit:',
        alternatives: MOCK_ADVERSARIAL_DESK_ALTERNATIVES,
      };
    }

    return {
      reply:
        'Found 3 pre-vetted warm cream Shopify chairs under $180 that fit Zone 1 with full 24" pull-out clearance:',
      alternatives: MOCK_CHAIR_ALTERNATIVES,
    };
  }

  const res = await fetch(`${API_BASE_URL}/api/session/${params.sessionId}/thread`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      utterance: params.utterance,
      pinned_zone_id: params.pinnedZoneId ?? undefined,
      pinned_item_id: params.pinnedItemId ?? undefined,
    }),
  });
  if (!res.ok) throw new Error(`Thread request failed (${res.status})`);
  const raw = await res.json();

  // Normalize backend ThreadAlternativeCard[] -> AlternativeSKUCard[]
  const alternatives: AlternativeSKUCard[] = (raw.alternatives ?? []).map(
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (a: any) => {
      if (a.sku) {
        return {
          sku_id: String(a.sku.sku_id),
          shopify_gid: String(a.sku.gid ?? ""),
          title: String(a.sku.title),
          merchant: String(a.sku.merchant_name ?? "Shopify Store"),
          price_usd: Number(a.sku.price_usd ?? 0),
          price_delta_usd: Number(a.price_delta_usd ?? 0),
          width_in: a.sku.dimensions?.width_in ?? null,
          fit_delta_label: String(a.delta_badge ?? ""),
          hook_blocked: Boolean(a.hook_blocked),
          block_reason: a.block_reason ?? null,
          image_url: String(a.sku.image_url ?? ""),
          zone_id: String(a.target_zone_id ?? "Z1"),
          target_item_id: String(a.target_item_id ?? a.sku.sku_id),
        };
      }
      return a as AlternativeSKUCard;
    }
  );

  return {
    reply: String(raw.reply ?? ""),
    alternatives,
    executed_swap: raw.executed_swap ? normalizeSwapRaw(raw.executed_swap) : null,
  };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function normalizeSwapRaw(raw: any): SwapResponse {
  const updatedItems = Array.isArray(raw.verified_items)
    ? // eslint-disable-next-line @typescript-eslint/no-explicit-any
      raw.verified_items.map((s: any, i: number) => normalizeShopifySKU(s, i))
    : undefined;
  const swapped = raw.swapped_item
    ? normalizeShopifySKU(raw.swapped_item, 0)
    : undefined;
  const render = raw.render ? normalizeRenderReady(raw.render).version : raw.new_version;

  return {
    allowed: true,
    updated_item: swapped,
    updated_items: updatedItems,
    updated_checkouts: raw.checkouts ? normalizeCheckouts(raw.checkouts) : undefined,
    updated_total_usd: raw.total_usd !== undefined ? Number(raw.total_usd) : undefined,
    new_version: render,
  };
}

export async function executeSurgicalSwap(params: {
  sessionId: string;
  zoneId: string;
  targetItemId: string;
  newSkuId: string;
  variantId?: string;
  useMock: boolean;
  currentItems?: VerifiedCartItem[];
  nextVersionNumber?: number;
  mockPresetId?: string | null;
}): Promise<SwapResponse> {
  if (params.useMock) {
    await sleep(900);
    if (params.newSkuId === "exec-desk-72") {
      return {
        allowed: false,
        hook_deny_reason:
          'verify_bundle.py DENY: 72.0" Executive Desk exceeds 41.5" usable width in Zone 1 (+28.5" overflow).',
      };
    }

    const preset =
      DEMO_PRESETS.find((p) => p.id === params.mockPresetId) || DEMO_PRESETS[0];
    const alt =
      [...MOCK_CHAIR_ALTERNATIVES, ...MOCK_ADVERSARIAL_DESK_ALTERNATIVES].find(
        (a) => a.sku_id === params.newSkuId
      );

    const existing = params.currentItems?.find((i) => i.item_id === params.targetItemId);
    const updatedItem: VerifiedCartItem = alt
      ? {
          ...(existing ?? {
            item_id: params.targetItemId,
            pin_number: 2,
            zone_id: params.zoneId,
            category: "Chair",
            zone_width_in: 43.5,
            depth_in: 24,
            height_in: 36,
            selected_variant_id: "var-cream",
            variants: [],
            pin_position: { x: 436, y: 635 },
          }),
          sku_id: alt.sku_id,
          shopify_gid: alt.shopify_gid,
          title: alt.title,
          merchant: alt.merchant,
          price_usd: alt.price_usd,
          width_in: alt.width_in ?? 24.5,
          fit_state: "verified",
          fit_label: `Verified Fit · ${(alt.width_in ?? 24.5).toFixed(1)}" ≤ 43.5"`,
          image_url: alt.image_url,
          stock_verified_at: Date.now(),
        }
      : {
          ...(existing as VerifiedCartItem),
          selected_variant_id: params.variantId ?? existing?.selected_variant_id ?? "",
          stock_verified_at: Date.now(),
        };

    const nextItems = (params.currentItems ?? []).map((i) =>
      i.item_id === params.targetItemId ? updatedItem : i
    );
    const updatedTotal = nextItems.reduce((sum, i) => sum + i.price_usd, 0);

    return {
      allowed: true,
      updated_item: updatedItem,
      updated_total_usd: Math.round(updatedTotal * 100) / 100,
      new_version: {
        version_id: `v${params.nextVersionNumber ?? 2}`,
        label: alt ? `Swapped → ${alt.title}` : `Re-rendered finish`,
        image_url: preset.rendered_v2_image_url,
        decisions_qa: {
          no_clipping: true,
          room_preserved: true,
          scale_honest: true,
          sku_fidelity: 3,
          confidence_band: "high_pass",
          latency_ms: 176,
          output_tokens: 0,
          repaired: false,
        },
        created_at: Date.now(),
      },
    };
  }

  const res = await fetch(`${API_BASE_URL}/api/session/${params.sessionId}/swap`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      zone_id: params.zoneId,
      target_item_id: params.targetItemId,
      new_sku_id: params.newSkuId,
      variant_id: params.variantId,
    }),
  });

  if (res.status === 422) {
    const errPayload = await res.json();
    return {
      allowed: false,
      hook_deny_reason:
        errPayload.reason ||
        errPayload.detail?.reason ||
        (typeof errPayload.detail === "string" ? errPayload.detail : null) ||
        "Blocked by hooks.json",
    };
  }

  if (!res.ok) throw new Error(`Swap failed (${res.status})`);
  return normalizeSwapRaw(await res.json());
}

export async function patchZoneOverride(params: {
  sessionId: string;
  zoneId: string;
  overrideWidthIn: number;
  overrideDepthIn: number;
  useMock: boolean;
  currentItems?: VerifiedCartItem[];
}): Promise<ZoneOverrideResponse> {
  if (params.useMock) {
    await sleep(120);
    const usable = Math.max(0, params.overrideWidthIn - 2.0);
    const updatedItems = (params.currentItems ?? []).map((item) => {
      if (item.zone_id !== params.zoneId || !item.width_in) return item;
      const fits = item.width_in <= usable;
      return {
        ...item,
        zone_width_in: params.overrideWidthIn,
        fit_state: fits ? ("verified" as const) : ("blocked" as const),
        fit_label: fits
          ? `Verified Fit · ${item.width_in.toFixed(1)}" ≤ ${params.overrideWidthIn.toFixed(1)}"`
          : `Blocked by Hook · ${item.width_in.toFixed(1)}" > ${usable.toFixed(1)}" usable`,
      };
    });

    const blocked = updatedItems.filter((i) => i.fit_state === "blocked");
    return {
      zone_id: params.zoneId,
      width_in: params.overrideWidthIn,
      depth_in: params.overrideDepthIn,
      updated_items: updatedItems,
      hook_traces: [
        {
          id: `override-${Date.now()}`,
          decision: blocked.length > 0 ? "DENY" : "ALLOW",
          timestamp: "LIVE",
          tool_name: "verify_bundle.py (measure_override)",
          summary:
            blocked.length > 0
              ? `DENY after measure override (${params.overrideWidthIn.toFixed(1)}" W): ${blocked[0].title} exceeds usable width`
              : `ALLOW after measure override (${params.overrideWidthIn.toFixed(1)}" W): all items fit with 2" margin`,
        },
      ],
    };
  }

  const res = await fetch(`${API_BASE_URL}/api/session/${params.sessionId}/zone`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      zone_id: params.zoneId,
      override_width_in: params.overrideWidthIn,
      override_depth_in: params.overrideDepthIn,
    }),
  });
  if (!res.ok) throw new Error(`Zone override failed (${res.status})`);
  const raw = await res.json();

  const updatedItems = Array.isArray(raw.verified_items)
    ? // eslint-disable-next-line @typescript-eslint/no-explicit-any
      raw.verified_items.map((s: any, idx: number) =>
        normalizeShopifySKU(s, idx, params.overrideWidthIn)
      )
    : params.currentItems ?? [];

  const hookNorm = raw.hook_event ? normalizeHookEvent(raw.hook_event) : null;

  return {
    zone_id: params.zoneId,
    width_in: Number(raw.updated_zone?.width_in ?? params.overrideWidthIn),
    depth_in: Number(raw.updated_zone?.depth_in ?? params.overrideDepthIn),
    updated_items: updatedItems,
    hook_traces: hookNorm?.traces ?? [],
  };
}

export async function fetchBenchmarkData(useMock: boolean): Promise<BenchmarkData> {
  if (useMock) return MOCK_BENCHMARK_DATA;
  try {
    const res = await fetch(`${API_BASE_URL}/api/benchmark`);
    if (!res.ok) return MOCK_BENCHMARK_DATA;
    const raw = await res.json();
    if (Array.isArray(raw.comparison_rows) && Array.isArray(raw.room_samples)) {
      return raw as BenchmarkData;
    }
    return MOCK_BENCHMARK_DATA;
  } catch {
    return MOCK_BENCHMARK_DATA;
  }
}
