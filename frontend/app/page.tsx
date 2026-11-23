"use client";

import React, { useEffect, useRef, useState } from "react";
import { Compass, Moon, RotateCcw, Sun } from "lucide-react";
import type {
  AlternativeSKUCard,
  BenchmarkData,
  CartReadyEvent,
  CatalogReadyEvent,
  DemoPreset,
  DetectedZone,
  HookEvent,
  RenderVersion,
  ScaleReadyEvent,
  SpaceScope,
  ThreadMessage,
  VerifiedCartItem,
} from "@/types/clearbuy";
import type { ProcessedRoomImage } from "@/lib/imageUtils";
import { MOCK_BENCHMARK_DATA } from "@/lib/mockData";
import {
  DEFAULT_USE_MOCK,
  executeSurgicalSwap,
  fetchBenchmarkData,
  patchZoneOverride,
  sendThreadUtterance,
  startSessionStream,
} from "@/lib/sseClient";
import { CaptureCanvas } from "@/components/CaptureCanvas";
import { RoomCanvas, type CanvasViewMode } from "@/components/RoomCanvas";
import { GlassBoxRail } from "@/components/GlassBoxRail";
import { ShopifyCommerceRail } from "@/components/ShopifyCommerceRail";
import { VoiceSpatialThread } from "@/components/VoiceSpatialThread";
import { BenchmarkDrawer } from "@/components/BenchmarkDrawer";

export default function DatumStudioPage() {
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [appPhase, setAppPhase] = useState<"capture" | "studio">("capture");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [activePresetId, setActivePresetId] = useState<string | null>(null);

  // Room images / multi-angle tabs
  const [angleTabs, setAngleTabs] = useState<
    { id: string; label: string; imageUrl: string }[]
  >([]);
  const [activeAngleId, setActiveAngleId] = useState<string>("angle-1");

  // Pipeline SSE states
  const [budgetUsd, setBudgetUsd] = useState<number>(450);
  const [scaleData, setScaleData] = useState<ScaleReadyEvent | null>(null);
  const [catalogData, setCatalogData] = useState<CatalogReadyEvent | null>(null);
  const [hookData, setHookData] = useState<HookEvent | null>(null);
  const [cartData, setCartData] = useState<CartReadyEvent | null>(null);
  const [versions, setVersions] = useState<RenderVersion[]>([]);
  const [activeVersionId, setActiveVersionId] = useState<string | null>(null);

  // Studio UI interaction states
  const [viewMode, setViewMode] = useState<CanvasViewMode>("blueprint");
  const [hoveredItemId, setHoveredItemId] = useState<string | null>(null);
  const [pinnedItem, setPinnedItem] = useState<VerifiedCartItem | null>(null);
  const [pinnedZone, setPinnedZone] = useState<DetectedZone | null>(null);
  const [isStreaming, setIsStreaming] = useState<boolean>(false);
  const [isRepairing, setIsRepairing] = useState<boolean>(false);
  const [elapsedSec, setElapsedSec] = useState<number>(0);
  const [errorBanner, setErrorBanner] = useState<string | null>(null);

  // Conversational Spatial Thread states
  const [messages, setMessages] = useState<ThreadMessage[]>([]);
  const [isSendingThread, setIsSendingThread] = useState<boolean>(false);
  const [isSwapping, setIsSwapping] = useState<boolean>(false);

  // Proof & Benchmark Drawer states (Component F)
  const [proofOpen, setProofOpen] = useState<boolean>(false);
  const [benchmarkData, setBenchmarkData] =
    useState<BenchmarkData>(MOCK_BENCHMARK_DATA);

  const abortRef = useRef<AbortController | null>(null);

  // Persist Darkroom Studio (default) / Light Atelier theme
  useEffect(() => {
    const saved = window.localStorage.getItem("datum-theme");
    if (saved === "dark" || saved === "light") {
      setTheme(saved);
    }
  }, []);

  useEffect(() => {
    document.documentElement.classList.toggle("theme-dark", theme === "dark");
    document.documentElement.classList.toggle("theme-light", theme === "light");
    window.localStorage.setItem("datum-theme", theme);
  }, [theme]);

  useEffect(() => {
    if (!isStreaming) return;
    const t0 = performance.now();
    const id = setInterval(() => {
      setElapsedSec((performance.now() - t0) / 1000);
    }, 100);
    return () => clearInterval(id);
  }, [isStreaming]);

  useEffect(() => {
    if (!proofOpen) return;
    fetchBenchmarkData(DEFAULT_USE_MOCK).then(setBenchmarkData);
  }, [proofOpen]);

  const resetToCapture = () => {
    abortRef.current?.abort();
    setAppPhase("capture");
    setSessionId(null);
    setScaleData(null);
    setCatalogData(null);
    setHookData(null);
    setCartData(null);
    setVersions([]);
    setActiveVersionId(null);
    setMessages([]);
    setPinnedItem(null);
    setPinnedZone(null);
    setErrorBanner(null);
    setIsStreaming(false);
    setElapsedSec(0);
  };

  const handleLaunchSession = async (payload: {
    images: ProcessedRoomImage[];
    prompt: string;
    budgetUsd: number;
    scope: SpaceScope;
    preset?: DemoPreset;
  }) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setScaleData(null);
    setCatalogData(null);
    setHookData(null);
    setCartData(null);
    setVersions([]);
    setActiveVersionId(null);
    setMessages([]);
    setPinnedItem(null);
    setPinnedZone(null);
    setErrorBanner(null);
    setBudgetUsd(payload.budgetUsd);
    setViewMode("blueprint");
    setElapsedSec(0);
    setIsStreaming(true);

    const isPreset = Boolean(payload.preset);
    setActivePresetId(payload.preset?.id ?? null);

    if (payload.preset) {
      setAngleTabs([
        {
          id: "angle-1",
          label: "Main View",
          imageUrl: payload.preset.room_image_url,
        },
      ]);
      setActiveAngleId("angle-1");
    } else {
      const tabs = payload.images.map((img, i) => ({
        id: `angle-${i + 1}`,
        label: i === 0 ? "Primary Wall" : `Angle ${i + 1}`,
        imageUrl: img.previewUrl,
      }));
      setAngleTabs(tabs);
      setActiveAngleId(tabs[0]?.id ?? "angle-1");
    }

    setAppPhase("studio");

    const runWithMock = DEFAULT_USE_MOCK || isPreset;

    await startSessionStream(
      {
        images: payload.images.map((i) => i.file),
        exifFocalMm:
          payload.images[0]?.exifFocalMm ?? payload.preset?.exif_focal_mm ?? null,
        prompt: payload.prompt,
        budgetUsd: payload.budgetUsd,
        scope: payload.scope,
        useMock: runWithMock,
        mockPresetId: payload.preset?.id ?? null,
      },
      {
        onSessionCreated: (id) => setSessionId(id),
        onScaleReady: (data) => {
          setScaleData(data);
          setViewMode("blueprint");
        },
        onCatalogReady: (data) => setCatalogData(data),
        onHookEvent: (data) => setHookData(data),
        onCartReady: (data) => setCartData(data),
        onRenderReady: (data) => {
          if (data.version.decisions_qa.repaired) {
            setIsRepairing(true);
            setTimeout(() => setIsRepairing(false), 1200);
          }
          // Apply backend hotspot pin coordinates onto cart items when provided
          if (data.version.hotspot_pins?.length) {
            setCartData((prev) => {
              if (!prev) return prev;
              const pins = data.version.hotspot_pins!;
              return {
                ...prev,
                items: prev.items.map((item) => {
                  const match = pins.find((p) => p.sku_id === item.sku_id);
                  return match
                    ? {
                        ...item,
                        pin_number: match.pin_number,
                        pin_position: { x: match.x_norm, y: match.y_norm },
                      }
                    : item;
                }),
              };
            });
          }
          setVersions([data.version]);
          setActiveVersionId(data.version.version_id);
          setViewMode("rendered");
          setIsStreaming(false);
        },
        onError: (msg) => {
          setErrorBanner(msg);
          setIsStreaming(false);
        },
      },
      controller.signal
    );
  };

  const handleOverrideZoneWidth = async (zone: DetectedZone, newWidthIn: number) => {
    if (!scaleData) return;
    setScaleData({
      ...scaleData,
      zones: scaleData.zones.map((z) =>
        z.zone_id === zone.zone_id
          ? { ...z, width_in: newWidthIn, user_overridden: true }
          : z
      ),
    });

    const resp = await patchZoneOverride({
      sessionId: sessionId || "mock",
      zoneId: zone.zone_id,
      overrideWidthIn: newWidthIn,
      overrideDepthIn: zone.depth_in,
      useMock: DEFAULT_USE_MOCK || Boolean(activePresetId),
      currentItems: cartData?.items,
    });

    if (cartData) {
      setCartData({ ...cartData, items: resp.updated_items });
    }
    if (hookData && resp.hook_traces.length > 0) {
      const hasDeny = resp.hook_traces.some((t) => t.decision === "DENY");
      setHookData({
        ...hookData,
        status: hasDeny ? "refused" : "verified",
        blocked_count: hasDeny ? hookData.blocked_count + 1 : hookData.blocked_count,
        traces: [...hookData.traces, ...resp.hook_traces],
      });
    }
  };

  const handleSelectVariant = (itemId: string, variantId: string) => {
    if (!cartData) return;
    const updatedItems = cartData.items.map((item) => {
      if (item.item_id !== itemId) return item;
      const chosen = item.variants.find((v) => v.variant_id === variantId);
      if (!chosen) return item;

      // Dynamically parse W x D x H from size variant label if available (e.g. '39.4" x 18.9" x 29.5"')
      let nextW = item.width_in ?? null;
      let nextD = item.depth_in ?? null;
      let nextH = item.height_in ?? null;
      let nextFitState = item.fit_state;
      let nextFitLabel = item.fit_label;

      const dimMatch = chosen.label.match(
        /(\d+(?:\.\d+)?)\s*(?:"|in|inch|inches)?\s*[x×]\s*(\d+(?:\.\d+)?)\s*(?:"|in|inch|inches)?(?:\s*[x×]\s*(\d+(?:\.\d+)?))?/i
      );
      if (dimMatch) {
        const parsedW = parseFloat(dimMatch[1]);
        const parsedD = parseFloat(dimMatch[2]);
        const parsedH = dimMatch[3] ? parseFloat(dimMatch[3]) : nextH;
        if (parsedW >= 6 && parsedW <= 140) {
          nextW = Math.round(parsedW * 10) / 10;
          const usableW = Math.max(1, Math.round((item.zone_width_in - 2.0) * 10) / 10);
          if (nextW <= usableW) {
            nextFitState = "verified";
            nextFitLabel = `Verified Fit · ${nextW.toFixed(1)}" <= ${usableW.toFixed(1)}"`;
          } else {
            nextFitState = "blocked";
            nextFitLabel = `Exceeds gap · ${nextW.toFixed(1)}" > ${usableW.toFixed(1)}"`;
          }
        }
        if (parsedD >= 6 && parsedD <= 140) {
          nextD = Math.round(parsedD * 10) / 10;
        }
        if (parsedH !== null && parsedH >= 4 && parsedH <= 120) {
          nextH = Math.round(parsedH * 10) / 10;
        }
      }

      return {
        ...item,
        selected_variant_id: chosen.variant_id,
        price_usd: chosen.price_usd,
        width_in: nextW,
        depth_in: nextD,
        height_in: nextH,
        fit_state: nextFitState,
        fit_label: nextFitLabel,
      };
    });
    const newTotal =
      Math.round(updatedItems.reduce((sum, i) => sum + i.price_usd, 0) * 100) / 100;
    setCartData({
      ...cartData,
      items: updatedItems,
      total_usd: newTotal,
    });
  };

  const handleRerenderVariant = async (item: VerifiedCartItem) => {
    setIsSwapping(true);
    try {
      const res = await executeSurgicalSwap({
        sessionId: sessionId || "mock",
        zoneId: item.zone_id,
        targetItemId: item.item_id,
        newSkuId: item.sku_id,
        variantId: item.selected_variant_id,
        useMock: DEFAULT_USE_MOCK || Boolean(activePresetId),
        currentItems: cartData?.items,
        nextVersionNumber: versions.length + 1,
        mockPresetId: activePresetId,
      });

      if (!res.allowed) {
        setErrorBanner(res.hook_deny_reason || "Variant blocked by hooks.json");
        return;
      }

      if (cartData) {
        setCartData({
          ...cartData,
          items: res.updated_items ?? cartData.items,
          total_usd: res.updated_total_usd ?? cartData.total_usd,
          checkouts: res.updated_checkouts ?? cartData.checkouts,
        });
      }

      if (res.new_version) {
        setVersions((prev) => [...prev, res.new_version!]);
        setActiveVersionId(res.new_version.version_id);
        setViewMode("rendered");
      }
    } finally {
      setIsSwapping(false);
    }
  };

  const handleSendUtterance = async (utterance: string) => {
    setIsSendingThread(true);
    setMessages((prev) => [
      ...prev,
      {
        id: `u-${Date.now()}`,
        role: "user",
        text: utterance,
        pinned_chip: pinnedItem
          ? `@${pinnedItem.zone_id} · ${pinnedItem.category}`
          : pinnedZone
          ? `@${pinnedZone.zone_id}`
          : null,
        timestamp: Date.now(),
      },
    ]);

    try {
      const res = await sendThreadUtterance({
        sessionId: sessionId || "mock",
        utterance,
        pinnedZoneId: pinnedItem?.zone_id ?? pinnedZone?.zone_id ?? null,
        pinnedItemId: pinnedItem?.item_id ?? null,
        useMock: DEFAULT_USE_MOCK || Boolean(activePresetId),
      });

      if (res.executed_swap?.allowed && res.executed_swap.new_version) {
        const swap = res.executed_swap;
        if (cartData) {
          setCartData({
            ...cartData,
            items: swap.updated_items ?? cartData.items,
            total_usd: swap.updated_total_usd ?? cartData.total_usd,
            checkouts: swap.updated_checkouts ?? cartData.checkouts,
          });
        }
        setVersions((prev) => [...prev, swap.new_version!]);
        setActiveVersionId(swap.new_version!.version_id);
        setViewMode("rendered");
      }

      setMessages((prev) => [
        ...prev,
        {
          id: `a-${Date.now()}`,
          role: "assistant",
          text: res.reply,
          alternatives: res.alternatives,
          timestamp: Date.now(),
        },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          id: `err-${Date.now()}`,
          role: "assistant",
          text: `Could not route request: ${(err as Error).message}`,
          timestamp: Date.now(),
        },
      ]);
    } finally {
      setIsSendingThread(false);
    }
  };

  const handleSelectAlternative = async (alt: AlternativeSKUCard) => {
    setIsSwapping(true);
    try {
      const res = await executeSurgicalSwap({
        sessionId: sessionId || "mock",
        zoneId: alt.zone_id,
        targetItemId: alt.target_item_id,
        newSkuId: alt.sku_id,
        useMock: DEFAULT_USE_MOCK || Boolean(activePresetId),
        currentItems: cartData?.items,
        nextVersionNumber: versions.length + 1,
        mockPresetId: activePresetId,
      });

      if (!res.allowed) {
        setMessages((prev) => [
          ...prev,
          {
            id: `deny-${Date.now()}`,
            role: "assistant",
            text: res.hook_deny_reason || "Blocked by hooks.json",
            timestamp: Date.now(),
          },
        ]);
        return;
      }

      if (cartData) {
        setCartData({
          ...cartData,
          items:
            res.updated_items ??
            (res.updated_item
              ? cartData.items.map((item) =>
                  item.item_id === res.updated_item!.item_id
                    ? res.updated_item!
                    : item
                )
              : cartData.items),
          total_usd: res.updated_total_usd ?? cartData.total_usd,
          checkouts: res.updated_checkouts ?? cartData.checkouts,
        });
      }

      if (res.new_version) {
        setVersions((prev) => [...prev, res.new_version!]);
        setActiveVersionId(res.new_version.version_id);
        setViewMode("rendered");
      }

      setMessages((prev) => [
        ...prev,
        {
          id: `swapped-${Date.now()}`,
          role: "assistant",
          text: `Surgical swap verified by hooks.json + Decisions QA (${res.new_version?.decisions_qa.latency_ms ?? 176} ms). Saved as ${res.new_version?.version_id ?? "v2"}.`,
          timestamp: Date.now(),
        },
      ]);
    } finally {
      setIsSwapping(false);
    }
  };

  const handleRequestSwapForItem = (
    item: VerifiedCartItem,
    promptOverride?: string
  ) => {
    setPinnedZone(null);
    setPinnedItem(item);
    if (promptOverride) {
      handleSendUtterance(promptOverride);
    }
  };

  const activeAngleUrl =
    angleTabs.find((a) => a.id === activeAngleId)?.imageUrl ||
    angleTabs[0]?.imageUrl ||
    "";

  const activeVersion =
    versions.find((v) => v.version_id === activeVersionId) ||
    versions[versions.length - 1] ||
    null;

  return (
    <div className="h-screen w-screen flex flex-col bg-at-bg text-at-ink overflow-hidden transition-colors duration-200">
      {/* Top 48px Utility Bar (Section 03.A) */}
      <header className="h-12 px-4 border-b border-at-border bg-at-card flex items-center justify-between gap-3 shrink-0 z-40">
        {/* Left: Datum Wordmark + New Space */}
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={resetToCapture}
            className="flex items-center gap-2 cursor-pointer"
          >
            <span className="h-7 w-7 rounded-lg bg-at-cyan/15 border border-at-cyan/50 flex items-center justify-center text-at-cyan">
              <Compass className="h-4 w-4" />
            </span>
            <span className="text-sm font-semibold tracking-[-0.02em] text-at-ink">
              Datum
            </span>
          </button>

          {appPhase === "studio" && (
            <button
              type="button"
              onClick={resetToCapture}
              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-at-bg border border-at-border hover:border-at-cyan text-[11px] font-medium text-at-muted hover:text-at-ink cursor-pointer transition-colors"
            >
              <RotateCcw className="h-3 w-3" />
              New Space
            </button>
          )}
        </div>

        {/* Center: Studio Space Scope Chip (hidden on capture screen) */}
        <div className="hidden md:flex items-center gap-2.5">
          {appPhase === "studio" && (
            <span className="px-2.5 py-1 rounded-lg bg-at-bg border border-at-border text-[11px] font-mono text-at-muted">
              {scaleData?.scope_label ?? "Calibrating Space…"}
            </span>
          )}
        </div>

        {/* Right: Budget Progress + Light/Dark Toggle */}
        <div className="flex items-center gap-2">
          <div className="hidden sm:inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-at-bg border border-at-border text-[11px] font-mono tabular-nums-strict">
            <span className="text-at-muted">Budget</span>
            <span
              className={
                (cartData?.total_usd ?? 0) > budgetUsd
                  ? "text-at-coral font-semibold"
                  : "text-at-emerald font-semibold"
              }
            >
              ${(cartData?.total_usd ?? 0).toFixed(2)}
            </span>
            <span className="text-at-muted">/ ${budgetUsd.toFixed(2)}</span>
          </div>

          <button
            type="button"
            onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
            className="px-2.5 py-1.5 rounded-lg bg-at-bg border border-at-border hover:border-at-cyan text-xs font-medium text-at-ink inline-flex items-center gap-1.5 cursor-pointer transition-colors"
            aria-label="Toggle Dark or Light Mode"
          >
            {theme === "dark" ? (
              <>
                <Moon className="h-3.5 w-3.5 text-at-cyan" />
                <span className="hidden sm:inline">Dark</span>
              </>
            ) : (
              <>
                <Sun className="h-3.5 w-3.5 text-at-accent" />
                <span className="hidden sm:inline">Light</span>
              </>
            )}
          </button>
        </div>
      </header>

      {/* Main Content: Universal Capture OR 64/36 Darkroom Studio */}
      {appPhase === "capture" ? (
        <CaptureCanvas onLaunchSession={handleLaunchSession} />
      ) : (
        <main className="flex-1 flex flex-col lg:flex-row min-h-0 overflow-hidden">
          <section className="relative w-full lg:w-[64%] h-[55%] lg:h-full flex flex-col border-b lg:border-b-0 lg:border-r border-at-border min-h-0">
            {errorBanner && (
              <div className="px-4 py-2 bg-at-coral/12 border-b border-at-coral/40 text-xs font-mono text-at-coral flex items-center justify-between">
                <span>{errorBanner}</span>
                <button
                  type="button"
                  onClick={() => setErrorBanner(null)}
                  className="underline ml-3 cursor-pointer"
                >
                  Dismiss
                </button>
              </div>
            )}

            <RoomCanvas
              originalImageUrl={activeAngleUrl}
              scaleData={scaleData}
              versions={versions}
              activeVersionId={activeVersionId}
              onSelectVersion={setActiveVersionId}
              viewMode={viewMode}
              onChangeViewMode={setViewMode}
              cartItems={cartData?.items ?? []}
              hoveredItemId={hoveredItemId}
              onHoverItem={setHoveredItemId}
              onPinItem={(item) => {
                setPinnedZone(null);
                setPinnedItem(item);
              }}
              onSelectZone={(zone) => {
                setPinnedItem(null);
                setPinnedZone(zone);
              }}
              onOverrideZoneWidth={handleOverrideZoneWidth}
              isRendering={isStreaming}
              isRepairing={isRepairing}
              angleTabs={angleTabs}
              activeAngleId={activeAngleId}
              onSelectAngle={setActiveAngleId}
            />

            <VoiceSpatialThread
              messages={messages}
              pinnedItem={pinnedItem}
              pinnedZone={pinnedZone}
              onClearPin={() => {
                setPinnedItem(null);
                setPinnedZone(null);
              }}
              onSendUtterance={handleSendUtterance}
              onSelectAlternative={handleSelectAlternative}
              isSending={isSendingThread}
              isSwapping={isSwapping}
            />
          </section>

          <aside className="w-full lg:w-[36%] h-[45%] lg:h-full flex flex-col min-h-0 bg-at-card">
            {/* Live 4-Stage Glass-Box Verification Strip */}
            <GlassBoxRail
              scaleData={scaleData}
              catalogData={catalogData}
              hookData={hookData}
              cartData={cartData}
              decisionsQA={activeVersion?.decisions_qa ?? null}
              isStreaming={isStreaming}
              elapsedSec={elapsedSec}
            />

            <ShopifyCommerceRail
              cartData={cartData}
              budgetUsd={budgetUsd}
              isLoading={isStreaming}
              isSwapping={isSwapping}
              hoveredItemId={hoveredItemId}
              pinnedItemId={pinnedItem?.item_id ?? null}
              onHoverItem={setHoveredItemId}
              onSelectVariant={handleSelectVariant}
              onRerenderVariant={handleRerenderVariant}
              onRequestSwapForItem={handleRequestSwapForItem}
            />
          </aside>
        </main>
      )}

      {/* Slide-Over Proof & Benchmark Drawer (Component F) */}
      <BenchmarkDrawer
        open={proofOpen}
        onClose={() => setProofOpen(false)}
        data={benchmarkData}
      />
    </div>
  );
}
