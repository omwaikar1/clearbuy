import type {
  AlternativeSKUCard,
  BenchmarkData,
  CartReadyEvent,
  CatalogReadyEvent,
  DemoPreset,
  HookEvent,
  RenderReadyEvent,
  ScaleReadyEvent,
  SpaceScope,
} from "@/types/clearbuy";

export type RoomVibe = "scandi" | "midcentury" | "minimal";

export const ROOM_VIBES: { id: RoomVibe; label: string }[] = [
  { id: "scandi", label: "Scandi Warm" },
  { id: "midcentury", label: "Mid-Century" },
  { id: "minimal", label: "Minimalist" },
];

const VIBE_PALETTES: Record<
  RoomVibe,
  {
    wall: string;
    floor: string;
    desk: string;
    chair: string;
    chairStroke: string;
    lamp: string;
    sofa: string;
  }
> = {
  scandi: {
    wall: "#EFEAE2",
    floor: "#D5BFA8",
    desk: "#C99A6B",
    chair: "#E7DDD2",
    chairStroke: "#BFA992",
    lamp: "#D4AF37",
    sofa: "#E6DFD5",
  },
  midcentury: {
    wall: "#E7DFD5",
    floor: "#B58D67",
    desk: "#7C4D2B",
    chair: "#475569",
    chairStroke: "#334155",
    lamp: "#C8923B",
    sofa: "#C7A27C",
  },
  minimal: {
    wall: "#F4F3F0",
    floor: "#DDD7CE",
    desk: "#E2DCD3",
    chair: "#D6D3CD",
    chairStroke: "#A8A29E",
    lamp: "#57534E",
    sofa: "#EAE7E1",
  },
};

/**
 * Generates sunlit IKEA-Kreativ-inspired architectural room visuals that work 100% offline.
 */
export function makeSunlitRoomSvg(opts: {
  vibe?: RoomVibe;
  rendered: boolean;
  warmChair?: boolean;
  multiZone?: boolean;
}): string {
  const palette = VIBE_PALETTES[opts.vibe ?? "scandi"];
  const chairFill = opts.warmChair ? "#EDE2D4" : palette.chair;
  const chairStroke = opts.warmChair ? "#C6A488" : palette.chairStroke;

  const furniture = opts.rendered
    ? opts.multiZone
      ? `
        <ellipse cx="360" cy="545" rx="230" ry="30" fill="rgba(0,0,0,0.08)"/>
        <polygon points="145,505 565,505 610,625 95,625" fill="#D5C8B6" opacity="0.82" stroke="#B6A792" stroke-width="2"/>
        <rect x="135" y="335" width="380" height="125" rx="16" fill="${palette.sofa}" stroke="rgba(0,0,0,0.14)" stroke-width="2.5"/>
        <rect x="155" y="360" width="165" height="62" rx="10" fill="#F6F2EC" stroke="rgba(0,0,0,0.10)" stroke-width="1.5"/>
        <rect x="330" y="360" width="165" height="62" rx="10" fill="#F6F2EC" stroke="rgba(0,0,0,0.10)" stroke-width="1.5"/>
        <rect x="245" y="486" width="190" height="54" rx="10" fill="${palette.desk}" stroke="rgba(0,0,0,0.16)" stroke-width="2"/>
        <line x1="735" y1="215" x2="735" y2="495" stroke="${palette.lamp}" stroke-width="5"/>
        <ellipse cx="735" cy="495" rx="28" ry="8" fill="${palette.lamp}"/>
        <polygon points="703,215 767,215 754,158 716,158" fill="#FFF8E7" stroke="${palette.lamp}" stroke-width="2"/>
        <circle cx="735" cy="230" r="76" fill="#FDE68A" opacity="0.22"/>
      `
      : `
        <ellipse cx="438" cy="532" rx="175" ry="22" fill="rgba(0,0,0,0.10)"/>
        <rect x="268" y="346" width="340" height="18" rx="5" fill="${palette.desk}" stroke="rgba(0,0,0,0.16)" stroke-width="2"/>
        <rect x="288" y="364" width="12" height="158" fill="#27272A"/>
        <rect x="576" y="364" width="12" height="158" fill="#27272A"/>
        <rect x="278" y="518" width="36" height="8" rx="3" fill="#18181B"/>
        <rect x="562" y="518" width="36" height="8" rx="3" fill="#18181B"/>
        <path d="M554 346 L572 280 L536 264" fill="none" stroke="${palette.lamp}" stroke-width="4" stroke-linecap="round"/>
        <polygon points="520,258 554,268 544,286 512,276" fill="#FEF3C7" stroke="${palette.lamp}" stroke-width="1.5"/>
        <circle cx="526" cy="292" r="56" fill="#FDE68A" opacity="0.22"/>
        <rect x="386" y="324" width="96" height="90" rx="18" fill="${chairFill}" stroke="${chairStroke}" stroke-width="2.5"/>
        <rect x="378" y="416" width="112" height="24" rx="10" fill="${chairFill}" stroke="${chairStroke}" stroke-width="2.5"/>
        <line x1="434" y1="440" x2="434" y2="516" stroke="#52525B" stroke-width="8"/>
        <line x1="394" y1="526" x2="474" y2="526" stroke="#52525B" stroke-width="6" stroke-linecap="round"/>
      `
    : "";

  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 660">
    <defs>
      <linearGradient id="sun" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stop-color="#FFFBEB" stop-opacity="0.52"/>
        <stop offset="100%" stop-color="#FFFBEB" stop-opacity="0"/>
      </linearGradient>
    </defs>
    <rect x="0" y="0" width="1000" height="465" fill="${palette.wall}"/>
    <polygon points="0,0 115,48 115,465 0,560" fill="rgba(0,0,0,0.055)"/>
    <polygon points="1000,0 885,48 885,465 1000,560" fill="rgba(0,0,0,0.075)"/>
    <polygon points="120,40 430,40 540,465 80,465" fill="url(#sun)"/>
    <rect x="115" y="440" width="770" height="25" fill="#FFFFFF" opacity="0.85"/>
    <line x1="115" y1="440" x2="885" y2="440" stroke="rgba(0,0,0,0.08)" stroke-width="2"/>
    <polygon points="115,465 885,465 1000,660 0,660" fill="${palette.floor}"/>
    <line x1="250" y1="465" x2="180" y2="660" stroke="#000" stroke-opacity="0.08" stroke-width="2"/>
    <line x1="420" y1="465" x2="395" y2="660" stroke="#000" stroke-opacity="0.08" stroke-width="2"/>
    <line x1="590" y1="465" x2="615" y2="660" stroke="#000" stroke-opacity="0.08" stroke-width="2"/>
    <line x1="755" y1="465" x2="835" y2="660" stroke="#000" stroke-opacity="0.08" stroke-width="2"/>
    <rect x="760" y="92" width="105" height="373" fill="#FAF8F5" stroke="rgba(0,0,0,0.14)" stroke-width="2.5"/>
    <circle cx="776" cy="296" r="5" fill="#B48A5A"/>
    <rect x="206" y="382" width="18" height="29" rx="2" fill="#FFFFFF" stroke="#94A3B8" stroke-width="1.5"/>
    <rect x="211" y="389" width="8" height="5" rx="1" fill="#64748B"/>
    <rect x="211" y="399" width="8" height="5" rx="1" fill="#64748B"/>
    ${furniture}
  </svg>`;

  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

export const DEMO_PRESETS: DemoPreset[] = [
  {
    id: "tight-nook",
    title: "NYC Apartment Alcove",
    subtitle: '55.6" measured gap · Desk, chair & lamp · $480',
    scope: "nook",
    budget_usd: 480,
    prompt:
      "Set up a compact home office desk, ergonomic chair, and table lamp in this alcove under $480.",
    room_image_url: "/demos/nyc_1_original.jpg",
    rendered_image_url: "/demos/nyc_4_render_v1.jpg",
    rendered_v2_image_url: "/demos/nyc_5_swap_v2.jpg",
    exif_focal_mm: 26,
  },
  {
    id: "desk-upgrade",
    title: "Existing Desk Upgrade",
    subtitle: "Keep existing setup · New chair & lamp · $340",
    scope: "upgrade",
    budget_usd: 340,
    prompt:
      "Keep my existing desk; replace the chair and add a warm task lamp under $340.",
    room_image_url: "/demos/real_desk_upgrade.jpg",
    rendered_image_url: "/demos/real_desk_upgrade.jpg",
    rendered_v2_image_url: "/demos/real_desk_upgrade.jpg",
    exif_focal_mm: 28,
  },
  {
    id: "full-living-room",
    title: "Full Living Room",
    subtitle: "Sofa, coffee table, rug & floor lamp · $1,350",
    scope: "full_room",
    budget_usd: 1350,
    prompt:
      "Furnish this whole living room—sofa, coffee table, rug, and floor lamp under $1,350.",
    room_image_url: "/demos/real_living_room.jpg",
    rendered_image_url: "/demos/real_living_room.jpg",
    rendered_v2_image_url: "/demos/real_living_room.jpg",
    exif_focal_mm: 28,
  },
];

function makeProductThumb(label: string, accent: string): string {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 180 180">
    <rect width="180" height="180" rx="14" fill="#F3EFE9"/>
    <circle cx="90" cy="78" r="40" fill="${accent}" opacity="0.18"/>
    <rect x="44" y="64" width="92" height="14" rx="4" fill="${accent}"/>
    <rect x="54" y="78" width="8" height="44" rx="2" fill="#52525B"/>
    <rect x="118" y="78" width="8" height="44" rx="2" fill="#52525B"/>
    <text x="90" y="152" text-anchor="middle" fill="#6B655E" font-family="monospace" font-size="11" font-weight="600">${label}</text>
  </svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

export function buildMockPipelinePayloads(params: {
  sessionId: string;
  scope: SpaceScope;
  budgetUsd: number;
  exifFocalMm: number | null;
  renderedImageUrl: string;
}): {
  scale: ScaleReadyEvent;
  catalog: CatalogReadyEvent;
  hook: HookEvent;
  cart: CartReadyEvent;
  render: RenderReadyEvent;
} {
  const isFullRoom = params.scope === "full_room";
  const now = Date.now();

  const scale: ScaleReadyEvent = {
    session_id: params.sessionId,
    detected_scope: isFullRoom ? "full_room" : "nook",
    scope_label: isFullRoom ? "Full Room · 3 Zones" : 'Wall Space · 43.5" W',
    calibration_layer: "layer1_anchor",
    tolerance_in: 1.5,
    exif_focal_mm: params.exifFocalMm ?? 26,
    anchors: [
      {
        id: "anchor-outlet",
        label: "US Outlet",
        known_size_label: '4.5" H',
        px_per_in: 14.2,
        bbox: [576, 204, 624, 226],
        confidence: 0.96,
      },
      {
        id: "anchor-door",
        label: "Interior Door",
        known_size_label: '80.0" H',
        px_per_in: 14.4,
        bbox: [139, 760, 704, 865],
        confidence: 0.94,
      },
    ],
    protected_anchors:
      params.scope === "upgrade"
        ? [{ label: "Existing Desk", bbox: [520, 265, 795, 608] }]
        : [],
    cross_anchor_skew_pct: 1.4,
    foreshortening_warning: false,
    skew_warning: null,
    zones: isFullRoom
      ? [
          {
            zone_id: "Z1",
            label: "Sofa Wall",
            bbox: [490, 130, 725, 540],
            width_in: 92.0,
            depth_in: 38.0,
            clearance_in: 24,
          },
          {
            zone_id: "Z2",
            label: "Center Floor",
            bbox: [735, 220, 920, 560],
            width_in: 64.0,
            depth_in: 42.0,
            clearance_in: 24,
          },
          {
            zone_id: "Z3",
            label: "Lamp Corner",
            bbox: [240, 690, 760, 795],
            width_in: 24.0,
            depth_in: 24.0,
          },
        ]
      : [
          {
            zone_id: "Z1",
            label: "Wall Space",
            bbox: [460, 260, 815, 620],
            width_in: 43.5,
            depth_in: 30.0,
            clearance_in: 24,
          },
        ],
    elapsed_ms: 1920,
  };

  const catalog: CatalogReadyEvent = {
    mcp_calls: [
      'search_catalog(q="compact standing desk 40 inch", country="US")',
      'search_catalog(q="ergonomic home office chair", country="US")',
      'search_catalog(q="warm brass task lamp", country="US")',
    ],
    stores_scanned: 14,
    skus_screened: 15,
    catalog_gate_ms: 192,
    candidates: [
      {
        sku_id: "garvee-desk-40",
        shopify_gid: "gid://shopify/Product/89412038412",
        title: 'Garvee 40" Electric Standing Desk',
        merchant: "Garvee Home",
        price_usd: 129.95,
        width_in: 40.0,
        depth_in: 24.0,
        height_in: 28.5,
        harmony_score: 3,
        category_match: true,
        image_url: makeProductThumb('40" DESK', "#C99A6B"),
      },
      {
        sku_id: "branch-chair-ergo",
        shopify_gid: "gid://shopify/Product/91204411209",
        title: "Branch Verve Ergonomic Task Chair",
        merchant: "Branch Furniture",
        price_usd: 212.99,
        width_in: 25.0,
        depth_in: 24.5,
        height_in: 38.0,
        harmony_score: 3,
        category_match: true,
        image_url: makeProductThumb('25" CHAIR', "#64748B"),
      },
      {
        sku_id: "lumina-lamp-warm",
        shopify_gid: "gid://shopify/Product/77812399104",
        title: "Lumina Studio Warm Brass Task Lamp",
        merchant: "Lumina Goods",
        price_usd: 48.0,
        width_in: null,
        depth_in: null,
        height_in: 17.5,
        dimensions_unverified: true,
        harmony_score: 2,
        category_match: true,
        image_url: makeProductThumb("TASK LAMP", "#D4AF37"),
      },
    ],
    elapsed_ms: 2640,
  };

  const hook: HookEvent = {
    status: "self_corrected",
    blocked_count: 1,
    traces: [
      {
        id: "h-1",
        decision: "DENY",
        timestamp: "00:02.91",
        tool_name: "write_to_file(/workspace/cart_proposal.json)",
        summary: 'DENY 48.0" desk exceeds 43.5" Wall Space (requires 2.0" wall margin → max 41.5")',
        detail:
          '{"decision":"deny","reason":"48.0 in desk exceeds 41.5 in usable width in Z1 (43.5 in - 2.0 in buffer)"}',
      },
      {
        id: "h-2",
        decision: "RETRY",
        timestamp: "00:03.38",
        tool_name: "gemini-4-hydrogen(combinatorial_rebalance)",
        summary: 'AUTO-SWAP → Garvee 40.0" Standing Desk ($129.95) + 24.0" chair pull-out verified',
      },
      {
        id: "h-3",
        decision: "ALLOW",
        timestamp: "00:03.72",
        tool_name: "write_to_file(/workspace/cart_proposal.json)",
        summary: `ALLOW 3 SKUs · 40.0" ≤ 41.5" usable · 24.0" clearance OK · $390.94 ≤ $${params.budgetUsd.toFixed(2)}`,
        detail: '{"decision":"allow","margin_in":3.5,"budget_remaining_usd":59.06}',
      },
    ],
    elapsed_ms: 3720,
  };

  const cart: CartReadyEvent = {
    items: [
      {
        item_id: "item-desk-1",
        pin_number: 1,
        zone_id: "Z1",
        sku_id: "garvee-desk-40",
        shopify_gid: "gid://shopify/Product/89412038412",
        title: 'Garvee 40" Compact Standing Desk',
        category: "Desk",
        merchant: "Garvee Home",
        price_usd: 129.95,
        width_in: 40.0,
        depth_in: 24.0,
        height_in: 28.5,
        zone_width_in: 43.5,
        fit_state: "verified",
        fit_label: 'Verified Fit · 40.0" ≤ 43.5"',
        image_url: makeProductThumb('40" DESK', "#C99A6B"),
        stock_verified_at: now - 14000,
        selected_variant_id: "var-oak",
        variants: [
          { variant_id: "var-oak", label: "Warm Oak", color_hex: "#C99A6B", price_usd: 129.95, in_stock: true },
          { variant_id: "var-walnut", label: "Walnut", color_hex: "#7C4D2B", price_usd: 134.95, in_stock: true },
          { variant_id: "var-black", label: "Matte Black", color_hex: "#27272A", price_usd: 129.95, in_stock: true },
        ],
        pin_position: { x: 345, y: 545 },
      },
      {
        item_id: "item-chair-2",
        pin_number: 2,
        zone_id: "Z1",
        sku_id: "branch-chair-ergo",
        shopify_gid: "gid://shopify/Product/91204411209",
        title: "Branch Verve Ergonomic Chair",
        category: "Chair",
        merchant: "Branch Furniture",
        price_usd: 212.99,
        width_in: 25.0,
        depth_in: 24.5,
        height_in: 38.0,
        zone_width_in: 43.5,
        fit_state: "verified",
        fit_label: 'Verified Fit · 25.0" + 24" pull-out',
        image_url: makeProductThumb('25" CHAIR', "#64748B"),
        stock_verified_at: now - 11000,
        selected_variant_id: "var-slate",
        variants: [
          { variant_id: "var-slate", label: "Slate", color_hex: "#475569", price_usd: 212.99, in_stock: true },
          { variant_id: "var-cream", label: "Warm Cream", color_hex: "#E8D5C4", price_usd: 179.99, in_stock: true },
          { variant_id: "var-sage", label: "Sage", color_hex: "#6B8E78", price_usd: 212.99, in_stock: true },
        ],
        pin_position: { x: 436, y: 635 },
      },
      {
        item_id: "item-lamp-3",
        pin_number: 3,
        zone_id: "Z1",
        sku_id: "lumina-lamp-warm",
        shopify_gid: "gid://shopify/Product/77812399104",
        title: "Lumina Studio Warm Task Lamp",
        category: "Lamp",
        merchant: "Lumina Goods",
        price_usd: 48.0,
        width_in: null,
        depth_in: null,
        height_in: 17.5,
        zone_width_in: 43.5,
        fit_state: "unverified",
        fit_label: "Unverified Specs · Check Seller",
        image_url: makeProductThumb("TASK LAMP", "#D4AF37"),
        stock_verified_at: now - 9000,
        selected_variant_id: "var-brass",
        variants: [
          { variant_id: "var-brass", label: "Brushed Brass", color_hex: "#D4AF37", price_usd: 48.0, in_stock: true },
          { variant_id: "var-linen", label: "Warm Linen", color_hex: "#E7DFD1", price_usd: 48.0, in_stock: true },
        ],
        pin_position: { x: 545, y: 428 },
      },
    ],
    total_usd: 390.94,
    budget_usd: params.budgetUsd,
    checkouts: [
      {
        merchant: "Garvee Home",
        item_count: 1,
        subtotal_usd: 129.95,
        checkout_id: "ucp_chk_garvee_9821",
        continue_url: "https://shop.app/checkout/clearbuy-garvee-demo",
        ucp_payload: {
          protocol: "UCP/1.0",
          merchant: "Garvee Home",
          line_items: [{ gid: "gid://shopify/Product/89412038412", variant: "var-oak", quantity: 1, price_minor: 12995 }],
        },
      },
      {
        merchant: "Branch Furniture",
        item_count: 1,
        subtotal_usd: 212.99,
        checkout_id: "ucp_chk_branch_4410",
        continue_url: "https://shop.app/checkout/clearbuy-branch-demo",
        ucp_payload: {
          protocol: "UCP/1.0",
          merchant: "Branch Furniture",
          line_items: [{ gid: "gid://shopify/Product/91204411209", variant: "var-slate", quantity: 1, price_minor: 21299 }],
        },
      },
      {
        merchant: "Lumina Goods",
        item_count: 1,
        subtotal_usd: 48.0,
        checkout_id: "ucp_chk_lumina_1190",
        continue_url: "https://shop.app/checkout/clearbuy-lumina-demo",
        ucp_payload: {
          protocol: "UCP/1.0",
          merchant: "Lumina Goods",
          line_items: [{ gid: "gid://shopify/Product/77812399104", variant: "var-brass", quantity: 1, price_minor: 4800 }],
        },
      },
    ],
    protocol_steps: ["search_catalog", "get_product", "create_checkout"],
    elapsed_ms: 4100,
  };

  const render: RenderReadyEvent = {
    version: {
      version_id: "v1",
      label: "Initial Verified Render",
      image_url: params.renderedImageUrl,
      decisions_qa: {
        no_clipping: true,
        room_preserved: true,
        scale_honest: true,
        sku_fidelity: 3,
        confidence_band: "high_pass",
        latency_ms: 184,
        output_tokens: 0,
        repaired: false,
      },
      created_at: Date.now(),
    },
    elapsed_ms: 6200,
  };

  return { scale, catalog, hook, cart, render };
}

export const MOCK_CHAIR_ALTERNATIVES: AlternativeSKUCard[] = [
  {
    sku_id: "branch-cream-179",
    shopify_gid: "gid://shopify/Product/91204411888",
    title: "Solis Bouclé Cream Task Chair",
    merchant: "Branch Furniture",
    price_usd: 179.99,
    price_delta_usd: -33.0,
    width_in: 24.5,
    fit_delta_label: 'Fits 24.5" W',
    hook_blocked: false,
    image_url: makeProductThumb("CREAM CHAIR", "#E8D5C4"),
    zone_id: "Z1",
    target_item_id: "item-chair-2",
  },
  {
    sku_id: "nordic-oat-164",
    shopify_gid: "gid://shopify/Product/88412900412",
    title: "Nordic Oat Linen Swivel Chair",
    merchant: "Nordic Loft",
    price_usd: 164.0,
    price_delta_usd: -48.99,
    width_in: 23.5,
    fit_delta_label: 'Fits 23.5" W',
    hook_blocked: false,
    image_url: makeProductThumb("OAT CHAIR", "#D8C3A5"),
    zone_id: "Z1",
    target_item_id: "item-chair-2",
  },
  {
    sku_id: "studio-sand-149",
    shopify_gid: "gid://shopify/Product/80221933100",
    title: "Cove Sand Compact Desk Chair",
    merchant: "Garvee Home",
    price_usd: 149.5,
    price_delta_usd: -63.49,
    width_in: 22.8,
    fit_delta_label: 'Fits 22.8" W',
    hook_blocked: false,
    image_url: makeProductThumb("SAND CHAIR", "#C9B79C"),
    zone_id: "Z1",
    target_item_id: "item-chair-2",
  },
];

export const MOCK_ADVERSARIAL_DESK_ALTERNATIVES: AlternativeSKUCard[] = [
  {
    sku_id: "exec-desk-72",
    shopify_gid: "gid://shopify/Product/99102344101",
    title: '72" Walnut Executive Desk',
    merchant: "Heritage Office",
    price_usd: 549.0,
    price_delta_usd: +419.05,
    width_in: 72.0,
    fit_delta_label: '+28.5" over wall',
    hook_blocked: true,
    block_reason: 'Blocked by hooks.json (+28.5" over 43.5" wall & +$219 over budget)',
    image_url: makeProductThumb('72" BLOCKED', "#E11D48"),
    zone_id: "Z1",
    target_item_id: "item-desk-1",
  },
  {
    sku_id: "garvee-desk-40-walnut",
    shopify_gid: "gid://shopify/Product/89412038419",
    title: 'Garvee 40" Walnut Standing Desk',
    merchant: "Garvee Home",
    price_usd: 134.95,
    price_delta_usd: +5.0,
    width_in: 40.0,
    fit_delta_label: 'Fits 40.0" W',
    hook_blocked: false,
    image_url: makeProductThumb('40" WALNUT', "#7C4D2B"),
    zone_id: "Z1",
    target_item_id: "item-desk-1",
  },
  {
    sku_id: "flexi-desk-38",
    shopify_gid: "gid://shopify/Product/89412039991",
    title: 'FlexiNook 38" Solid Oak Desk',
    merchant: "FlexiNook",
    price_usd: 119.0,
    price_delta_usd: -10.95,
    width_in: 38.0,
    fit_delta_label: 'Fits 38.0" W',
    hook_blocked: false,
    image_url: makeProductThumb('38" OAK', "#C99A6B"),
    zone_id: "Z1",
    target_item_id: "item-desk-1",
  },
];

export const MOCK_BENCHMARK_DATA: BenchmarkData = {
  rooms_tested: 14,
  dataset_label: "12 Unseen NYU Depth V2 Kinect Rooms + 2 Live Venue Spaces",
  comparison_rows: [
    {
      method: "Baseline A: 1-Shot Image Gen",
      real_buyable_sku_pct: 0,
      physical_fit_pass_pct: 21.4,
      budget_compliance_pct: 14.3,
      visual_qa_pass_pct: 57.1,
      median_scale_err_in: "N/A (uncalibrated)",
    },
    {
      method: "Baseline B: Ungated Shopify Agent",
      real_buyable_sku_pct: 92.9,
      physical_fit_pass_pct: 50.0,
      budget_compliance_pct: 64.3,
      visual_qa_pass_pct: 71.4,
      median_scale_err_in: '±6.4"',
    },
    {
      method: "ClearBuy (Verified Spatial Compiler)",
      real_buyable_sku_pct: 100.0,
      physical_fit_pass_pct: 100.0,
      budget_compliance_pct: 100.0,
      visual_qa_pass_pct: 92.9,
      median_scale_err_in: '±1.4"',
    },
  ],
  ablation_rows: [
    {
      model_config: "gemini-4-neon (thinking_level=low)",
      multi_anchor_err_in: '±3.9"',
      coupled_bundle_pass_pct: 71.4,
      avg_latency_s: 1.4,
    },
    {
      model_config: "gemini-4-neon (thinking_level=xhigh)",
      multi_anchor_err_in: '±1.4"',
      coupled_bundle_pass_pct: 100.0,
      avg_latency_s: 2.3,
    },
  ],
  qa_catch_rate_pct: 91.7,
  room_samples: [
    {
      room_id: "nyu_012",
      room_label: "NYU Study Corner",
      image_url: makeSunlitRoomSvg({ vibe: "scandi", rendered: true }),
      kinect_gt_width_in: 44.2,
      clearbuy_est_width_in: 43.5,
      error_in: 0.7,
      calibration_layer: "Layer 1 (Anchor)",
      chosen_sku: 'Garvee 40" Standing Desk',
      blocked_sku: '48" Standing Desk (DENY)',
      status: "PASS",
      note: "Outlet + Door cross-check agreed within 2.1%.",
    },
    {
      room_id: "nyu_066",
      room_label: "NYU Narrow Bedroom Nook",
      image_url: makeSunlitRoomSvg({ vibe: "midcentury", rendered: true }),
      kinect_gt_width_in: 36.8,
      clearbuy_est_width_in: 37.9,
      error_in: 1.1,
      calibration_layer: "Layer 1 (Anchor)",
      chosen_sku: '34" Compact Writing Desk',
      blocked_sku: '42" Desk (DENY)',
      status: "FAILURE_FIXED",
      note: 'Caught 30"H regex trap; fixed via gemini-4-hydrogen structured W×D×H parser.',
    },
    {
      room_id: "nyu_104",
      room_label: "Blank Drywall Alcove",
      image_url: makeSunlitRoomSvg({ vibe: "minimal", rendered: true }),
      kinect_gt_width_in: 58.0,
      clearbuy_est_width_in: 55.2,
      error_in: 2.8,
      calibration_layer: "Layer 2 (Depth+EXIF)",
      chosen_sku: '52" Slim Bookcase + Chair',
      blocked_sku: null,
      status: "FALLBACK_PASS",
      note: 'Zero visible anchors; Depth-Anything-V2 + 26mm EXIF fired cleanly with amber ±3.8" badge.',
    },
    {
      room_id: "malin_01",
      room_label: "The Malin Chelsea — Nook",
      image_url: makeSunlitRoomSvg({ vibe: "scandi", rendered: true, multiZone: true }),
      kinect_gt_width_in: 45.0,
      clearbuy_est_width_in: 44.1,
      error_in: 0.9,
      calibration_layer: "Layer 1 (Anchor)",
      chosen_sku: 'Garvee 40" Desk + Branch Chair',
      blocked_sku: '72" Executive Desk (DENY)',
      status: "PASS",
      note: "Live venue photo verified against iPhone Measure.",
    },
  ],
  failure_audits: [
    {
      id: "fail-1",
      title: 'Height-vs-Width Regex Trap ("30\\"H" parsed as width)',
      room_ref: "nyu_066",
      what_broke:
        'Naive regex extracted "30" from "30\\"H x 48\\"W" and allowed an oversized 48" desk into a 36.8" gap.',
      how_we_fixed_it:
        "Replaced regex with gemini-4-hydrogen structured W×D×H JSON extraction and flagged omitted specs as amber Unverified Specs.",
    },
    {
      id: "fail-2",
      title: "Shopify Minor-Unit Cents Pricing ($129.95 read as $12,995)",
      room_ref: "nyu_019",
      what_broke:
        "shop.dev returned integer cents (12995), causing verify_bundle.py to falsely reject every valid cart.",
      how_we_fixed_it:
        "Normalized integer cents ÷ 100 inside shop_mcp.py before passing candidates to Managed Agents.",
    },
    {
      id: "fail-3",
      title: "Perspective Foreshortening on Angled Wall Shots",
      room_ref: "nyu_088",
      what_broke:
        'Single-anchor calibration drifted by 5.2" when the outlet was 4 feet closer to the camera than the target wall.',
      how_we_fixed_it:
        "Upgraded to gemini-4-neon xhigh multi-anchor cross-audit flagging >15% inter-anchor skew honestly in the UI.",
    },
  ],
};
