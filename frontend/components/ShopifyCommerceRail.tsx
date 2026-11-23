"use client";

import React, { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ExternalLink,
  RefreshCw,
  Ruler,
  ShieldAlert,
  Sparkles,
  Store,
  X,
} from "lucide-react";
import type { CartReadyEvent, VerifiedCartItem } from "@/types/clearbuy";

interface ShopifyCommerceRailProps {
  cartData: CartReadyEvent | null;
  budgetUsd: number;
  isLoading: boolean;
  isSwapping: boolean;
  hoveredItemId: string | null;
  pinnedItemId?: string | null;
  onHoverItem: (itemId: string | null) => void;
  onSelectVariant: (itemId: string, variantId: string) => void;
  onRerenderVariant: (item: VerifiedCartItem) => void;
  onRequestSwapForItem: (item: VerifiedCartItem, promptOverride?: string) => void;
}

export function ShopifyCommerceRail({
  cartData,
  budgetUsd,
  isLoading,
  isSwapping,
  hoveredItemId,
  pinnedItemId,
  onHoverItem,
  onSelectVariant,
  onRerenderVariant,
  onRequestSwapForItem,
}: ShopifyCommerceRailProps) {
  const [showUcpModal, setShowUcpModal] = useState(false);
  const [previewItem, setPreviewItem] = useState<VerifiedCartItem | null>(null);
  const [dirtyVariantItems, setDirtyVariantItems] = useState<Record<string, boolean>>({});
  const cardRefs = useRef<Record<string, HTMLDivElement | null>>({});

  useEffect(() => {
    if (!pinnedItemId) return;
    cardRefs.current[pinnedItemId]?.scrollIntoView({
      behavior: "smooth",
      block: "nearest",
    });
  }, [pinnedItemId]);

  useEffect(() => {
    if (!previewItem && !showUcpModal) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setPreviewItem(null);
        setShowUcpModal(false);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [previewItem, showUcpModal]);

  const totalUsd = cartData?.total_usd ?? 0;
  const budgetPct = Math.min(100, budgetUsd > 0 ? (totalUsd / budgetUsd) * 100 : 0);
  const isOverBudget = totalUsd > budgetUsd;

  return (
    <div className="flex-1 flex flex-col min-h-0 bg-at-card">
      {/* Spacious Scrollable Product Cards */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3 min-h-0">
        {isLoading && !cartData && (
          <>
            {[1, 2, 3].map((n) => (
              <div
                key={n}
                className="h-32 rounded-xl bg-at-bg border border-at-border p-3 animate-pulse flex gap-3"
              >
                <div className="h-18 w-18 rounded-lg bg-at-border shrink-0" />
                <div className="flex-1 space-y-2">
                  <div className="h-3.5 w-3/4 rounded bg-at-border" />
                  <div className="h-3 w-1/2 rounded bg-at-border" />
                  <div className="h-5 w-2/3 rounded bg-at-border" />
                </div>
              </div>
            ))}
          </>
        )}

        {cartData?.items.map((item) => {
          const isHovered = hoveredItemId === item.item_id;
          const needsRerender = Boolean(dirtyVariantItems[item.item_id]);
          return (
            <div
              key={item.item_id}
              ref={(el) => {
                cardRefs.current[item.item_id] = el;
              }}
              onMouseEnter={() => onHoverItem(item.item_id)}
              onMouseLeave={() => onHoverItem(null)}
              className={`rounded-xl p-3 bg-at-bg border transition-all space-y-2.5 ${
                isHovered || pinnedItemId === item.item_id
                  ? "border-at-cyan ring-1 ring-at-cyan/30"
                  : item.fit_state === "blocked"
                  ? "border-at-coral/70"
                  : "border-at-border hover:border-at-cyan/50"
              }`}
            >
              <div className="flex gap-3">
                <button
                  type="button"
                  onClick={() => setPreviewItem(item)}
                  title="Click to view full product photo"
                  className="relative h-20 w-20 rounded-xl overflow-hidden border border-at-border hover:border-at-cyan bg-at-card shrink-0 cursor-zoom-in group transition-colors"
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={item.image_url}
                    alt={item.title}
                    className="h-full w-full object-cover group-hover:scale-105 transition-transform duration-200"
                  />
                  <span className="absolute top-1 left-1 h-5 w-5 rounded-full bg-[#0C0D10]/90 border border-at-cyan text-[10px] font-mono font-bold text-white flex items-center justify-center">
                    {item.pin_number}
                  </span>
                </button>

                <div className="flex-1 min-w-0 flex flex-col justify-between gap-2">
                  {/* Top: Title + Price */}
                  <div className="flex items-start justify-between gap-2">
                    <h3 className="text-sm font-semibold text-at-ink leading-snug line-clamp-2">
                      {item.title}
                    </h3>
                    <span className="text-sm font-mono font-semibold tabular-nums-strict text-at-ink shrink-0">
                      ${item.price_usd.toFixed(2)}
                    </span>
                  </div>

                  {/* Middle: Segregated Store + Fit Badge */}
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="inline-flex items-center gap-1 text-xs text-at-muted">
                      <Store className="h-3 w-3 shrink-0" />
                      <span>{item.merchant}</span>
                      <span className="text-at-emerald font-medium">· In Stock</span>
                      {item.product_url && (
                        <a
                          href={item.product_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-at-muted hover:text-at-cyan transition-colors ml-0.5"
                          title="Open live Shopify merchant page"
                        >
                          <ExternalLink className="h-2.5 w-2.5" />
                        </a>
                      )}
                    </span>

                    {item.fit_state === "verified" && (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-at-emerald/10 border border-at-emerald/30 text-[11px] font-mono tabular-nums-strict text-at-emerald">
                        <CheckCircle2 className="h-3 w-3" />
                        {item.fit_label}
                      </span>
                    )}
                    {item.fit_state === "unverified" && (
                      <div className="flex items-center gap-1.5">
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-at-notice/10 border border-at-notice/40 text-[11px] text-at-notice">
                          <AlertTriangle className="h-3 w-3" />
                          Check size
                        </span>
                        <button
                          type="button"
                          onClick={() =>
                            onRequestSwapForItem(
                              item,
                              `Find a verified-size ${item.category.toLowerCase()} alternative`
                            )
                          }
                          className="px-2 py-0.5 rounded-full bg-at-card border border-at-border hover:border-at-cyan text-[11px] text-at-ink cursor-pointer"
                        >
                          Find fit
                        </button>
                      </div>
                    )}
                    {item.fit_state === "blocked" && (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-at-coral/10 border border-at-coral/40 text-[11px] text-at-coral">
                        <ShieldAlert className="h-3 w-3" />
                        {item.fit_label}
                      </span>
                    )}
                  </div>
                </div>
              </div>

              {/* Actual Size vs. Measured Room Gap Comparison Bar */}
              {(() => {
                const gapW = item.zone_width_in;
                const marginIn = 2.0;
                const usableW = Math.max(1, Number((gapW - marginIn).toFixed(1)));
                const itemW = item.width_in ?? null;
                const itemD = item.depth_in ?? null;
                const itemH = item.height_in ?? null;

                if (!gapW || gapW <= 0) return null;

                if (itemW !== null && itemW > 0) {
                  const spareIn = Number((usableW - itemW).toFixed(1));
                  const fits = spareIn >= 0;
                  const itemPct = Math.min(100, Math.round((itemW / gapW) * 100));
                  const marginPct = Math.min(12, Math.max(3, Math.round((marginIn / gapW) * 100)));
                  const sparePct = Math.max(0, 100 - itemPct - marginPct);

                  return (
                    <div className="rounded-lg bg-at-surface/60 border border-at-border/80 px-2.5 py-1.5 space-y-1">
                      <div className="flex items-center justify-between gap-2 text-[10px] font-mono tabular-nums-strict">
                        <span className="inline-flex items-center gap-1 font-sans font-medium text-at-muted">
                          <Ruler className="h-3 w-3 text-at-cyan" />
                          Size vs. Measured Gap
                        </span>
                        <span className={fits ? "text-at-emerald font-semibold" : "text-at-coral font-semibold"}>
                          {itemW.toFixed(1)}&quot; / {usableW.toFixed(1)}&quot; usable (
                          {fits ? `+${spareIn.toFixed(1)}" spare` : `${spareIn.toFixed(1)}" overflow`})
                        </span>
                      </div>

                      {/* Proportional Width Scale Bar */}
                      <div
                        className="h-2 w-full rounded-full bg-at-bg border border-at-border/70 overflow-hidden flex"
                        title={`Item ${itemW.toFixed(1)}" W inside ${gapW.toFixed(1)}" measured gap (${usableW.toFixed(1)}" usable + ${marginIn}" wall margin)`}
                      >
                        <div
                          className={`h-full transition-all duration-300 ${
                            fits ? "bg-at-emerald" : "bg-at-coral"
                          }`}
                          style={{ width: `${itemPct}%` }}
                        />
                        {sparePct > 0 && (
                          <div
                            className="h-full bg-at-cyan/20 border-l border-dashed border-at-cyan/50"
                            style={{ width: `${sparePct}%` }}
                          />
                        )}
                        <div
                          className="h-full bg-at-muted/20 border-l border-at-border"
                          style={{ width: `${marginPct}%` }}
                        />
                      </div>

                      {/* Exact Numeric Breakdown */}
                      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-0.5 text-[10px] font-mono tabular-nums-strict text-at-muted">
                        <span>
                          Item:{" "}
                          <strong className="text-at-ink">
                            {itemW.toFixed(1)}&quot;W
                            {itemD ? ` × ${itemD.toFixed(1)}"D` : ""}
                            {itemH ? ` × ${itemH.toFixed(1)}"H` : ""}
                          </strong>
                        </span>
                        <span>
                          Gap:{" "}
                          <strong className="text-at-ink">
                            {gapW.toFixed(1)}&quot;W
                          </strong>
                          {" "}({marginIn.toFixed(0)}&quot; margin)
                        </span>
                      </div>
                    </div>
                  );
                }

                return (
                  <div className="rounded-lg bg-at-notice/5 border border-at-notice/30 px-2.5 py-1.5 flex items-center justify-between gap-2 text-[10px]">
                    <span className="inline-flex items-center gap-1 font-sans text-at-notice">
                      <Ruler className="h-3 w-3" />
                      Measured Gap: {gapW.toFixed(1)}&quot; W ({usableW.toFixed(1)}&quot; usable)
                    </span>
                    <span className="text-at-muted font-mono">Merchant width unlisted</span>
                  </div>
                );
              })()}

              {/* Finish Swatches + 1-Click Re-Render Finish + Swap */}
              <div className="flex items-center justify-between gap-2 pt-2 border-t border-at-border flex-wrap">
                <div className="flex items-center gap-1.5 flex-wrap">
                  {item.variants.map((variant) => {
                    const active = variant.variant_id === item.selected_variant_id;
                    return (
                      <button
                        key={variant.variant_id}
                        type="button"
                        onClick={() => {
                          onSelectVariant(item.item_id, variant.variant_id);
                          setDirtyVariantItems((prev) => ({
                            ...prev,
                            [item.item_id]: true,
                          }));
                        }}
                        className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] border transition-colors cursor-pointer ${
                          active
                            ? "bg-at-card border-at-cyan text-at-ink font-medium"
                            : "bg-transparent border-at-border text-at-muted hover:text-at-ink"
                        }`}
                      >
                        <span
                          className="h-2.5 w-2.5 rounded-full border border-white/25"
                          style={{ backgroundColor: variant.color_hex }}
                        />
                        {variant.label}
                      </button>
                    );
                  })}
                </div>

                <div className="flex items-center gap-1.5 shrink-0">
                  {needsRerender && (
                    <button
                      type="button"
                      disabled={isSwapping}
                      onClick={() => {
                        setDirtyVariantItems((prev) => ({
                          ...prev,
                          [item.item_id]: false,
                        }));
                        onRerenderVariant(item);
                      }}
                      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-at-cyan text-[#0C0D10] text-[10px] font-semibold disabled:opacity-50 cursor-pointer"
                    >
                      <Sparkles className="h-3 w-3" />
                      Re-render finish
                    </button>
                  )}

                  <button
                    type="button"
                    onClick={() => onRequestSwapForItem(item)}
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-at-card border border-at-border hover:border-at-cyan text-[10px] font-mono text-at-muted hover:text-at-ink cursor-pointer"
                  >
                    <RefreshCw className="h-3 w-3" />
                    Swap
                  </button>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Sticky Combined Budget Bar + Checkout All + Per-Merchant UCP + Shop Pay Banner */}
      <div className="border-t border-at-border bg-at-card p-3 space-y-2.5 shrink-0">
        <div className="space-y-1">
          <div className="flex items-center justify-between text-xs font-mono tabular-nums-strict">
            <span className="text-at-muted">Verified Bundle Total</span>
            <span className={isOverBudget ? "text-at-coral" : "text-at-emerald"}>
              ${totalUsd.toFixed(2)} / ${budgetUsd.toFixed(2)}
            </span>
          </div>
          <div className="h-1.5 w-full rounded-full bg-at-bg overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-300 ${
                isOverBudget ? "bg-at-coral" : "bg-at-emerald"
              }`}
              style={{ width: `${budgetPct}%` }}
            />
          </div>
        </div>

        {cartData && cartData.checkouts.length > 0 ? (
          <div className="space-y-2">
            {cartData.checkouts.length > 1 && (
              <button
                type="button"
                onClick={() => {
                  cartData.checkouts.forEach((chk) => {
                    window.open(chk.continue_url, "_blank", "noopener,noreferrer");
                  });
                }}
                className="w-full h-10 px-3.5 rounded-xl bg-at-shop hover:opacity-95 text-white text-xs font-semibold flex items-center justify-between transition-opacity shadow-sm cursor-pointer"
              >
                <span>
                  Checkout All ({cartData.checkouts.length} Stores) via Shop Pay
                </span>
                <span className="inline-flex items-center gap-1.5 font-mono tabular-nums-strict shrink-0">
                  ${totalUsd.toFixed(2)}
                  <ExternalLink className="h-3.5 w-3.5" />
                </span>
              </button>
            )}

            <div className="flex flex-wrap gap-1.5">
              {cartData.checkouts.map((chk) => (
                <a
                  key={chk.checkout_id}
                  href={chk.continue_url}
                  target="_blank"
                  rel="noreferrer"
                  className={`flex-1 min-w-[110px] h-8 px-2.5 rounded-lg border text-[11px] font-medium flex items-center justify-between gap-1.5 transition-colors ${
                    cartData.checkouts.length === 1
                      ? "bg-at-shop border-at-shop text-white hover:opacity-95"
                      : "bg-at-bg border-at-border text-at-ink hover:border-at-shop hover:text-at-shop"
                  }`}
                >
                  <span className="truncate">Checkout at {chk.merchant}</span>
                  <span className="inline-flex items-center gap-1 font-mono tabular-nums-strict shrink-0">
                    ${chk.subtotal_usd.toFixed(2)}
                    <ExternalLink className="h-3 w-3 opacity-75" />
                  </span>
                </a>
              ))}
            </div>

            {/* Authentic Shop Pay Handoff Banner (Section 03.B Component D) */}
            <div className="flex items-center justify-center gap-2 pt-0.5 text-[10px] font-mono text-at-muted">
              <span className="px-1.5 py-0.5 rounded bg-at-shop/15 text-at-shop font-semibold">
                Shop Pay
              </span>
              <span>Native per-merchant Universal Commerce Protocol (UCP) handoff</span>
            </div>
          </div>
        ) : (
          <div className="h-9 rounded-xl bg-at-bg border border-at-border flex items-center justify-center text-[11px] font-mono text-at-muted">
            Awaiting hooks.json ALLOW before UCP checkout creation…
          </div>
        )}
      </div>

      {/* Inspect UCP Payload & GIDs Modal */}
      {showUcpModal && cartData && (
        <div className="fixed inset-0 z-50 bg-black/65 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="w-full max-w-2xl rounded-2xl bg-at-card border border-at-border shadow-2xl overflow-hidden flex flex-col max-h-[80vh]">
            <div className="px-4 py-3 border-b border-at-border flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold text-at-ink">
                  Live Shop MCP GIDs &amp; Per-Merchant UCP Payloads
                </h3>
                <p className="text-[11px] font-mono text-at-muted">
                  Direct HTTP JSON-RPC → https://mcp.shop.com/
                </p>
              </div>
              <button
                type="button"
                onClick={() => setShowUcpModal(false)}
                className="p-1.5 rounded-lg hover:bg-at-bg text-at-muted cursor-pointer"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="p-4 overflow-y-auto space-y-3 font-mono text-[11px]">
              {cartData.items.map((item) => (
                <div
                  key={item.item_id}
                  className="flex items-center justify-between px-2.5 py-1.5 rounded-lg bg-at-bg border border-at-border"
                >
                  <span className="text-at-ink truncate">{item.title}</span>
                  <span className="text-at-emerald shrink-0 ml-2">
                    {item.shopify_gid}
                  </span>
                </div>
              ))}
              <pre className="p-3 rounded-xl bg-at-bg border border-at-border text-at-muted overflow-x-auto">
                {JSON.stringify(cartData.checkouts, null, 2)}
              </pre>
            </div>
          </div>
        </div>
      )}
      {/* Product Image Lightbox Modal */}
      {previewItem && (
        <div
          className="fixed inset-0 z-50 bg-black/75 backdrop-blur-xs flex items-center justify-center p-4"
          onClick={() => setPreviewItem(null)}
        >
          <div
            className="w-full max-w-lg rounded-2xl bg-at-card border border-at-border shadow-2xl overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="px-4 py-3 border-b border-at-border flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="text-sm font-semibold text-at-ink truncate">
                  {previewItem.title}
                </p>
                <p className="text-xs text-at-muted">
                  {previewItem.merchant} · ${previewItem.price_usd.toFixed(2)}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setPreviewItem(null)}
                className="p-1.5 rounded-lg hover:bg-at-bg text-at-muted hover:text-at-ink cursor-pointer"
                aria-label="Close preview"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="bg-at-bg p-6 flex items-center justify-center max-h-[65vh]">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={previewItem.image_url}
                alt={previewItem.title}
                className="max-h-[55vh] w-auto max-w-full rounded-xl object-contain shadow-lg"
              />
            </div>
            <div className="px-4 py-3 border-t border-at-border flex items-center justify-between gap-2 text-xs">
              <span className="font-mono text-at-emerald">
                {previewItem.fit_label}
              </span>
              <span className="text-at-muted">
                Pin #{previewItem.pin_number} in room
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
