"use client";

import React, { useRef, useState } from "react";
import {
  ChevronDown,
  ChevronUp,
  Loader2,
  Mic,
  MicOff,
  Send,
  ShieldAlert,
  Sparkles,
  X,
} from "lucide-react";
import type {
  AlternativeSKUCard,
  DetectedZone,
  ThreadMessage,
  VerifiedCartItem,
} from "@/types/clearbuy";

interface VoiceSpatialThreadProps {
  messages: ThreadMessage[];
  pinnedItem: VerifiedCartItem | null;
  pinnedZone: DetectedZone | null;
  onClearPin: () => void;
  onSendUtterance: (utterance: string) => Promise<void>;
  onSelectAlternative: (alt: AlternativeSKUCard) => Promise<void>;
  isSending: boolean;
  isSwapping: boolean;
}

interface SpeechRecognitionLike {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((e: { results: ArrayLike<{ 0: { transcript: string } }> }) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
}

const QUICK_CHIPS = [
  "Swap the chair for a warmer cream fabric under $180",
  "Put a 72-inch executive desk there",
];

function formatZoneLabel(zoneId: string): string {
  const num = zoneId.replace(/\D+/g, "");
  return num ? `Zone ${num}` : zoneId;
}

export function VoiceSpatialThread({
  messages,
  pinnedItem,
  pinnedZone,
  onClearPin,
  onSendUtterance,
  onSelectAlternative,
  isSending,
  isSwapping,
}: VoiceSpatialThreadProps) {
  const [expanded, setExpanded] = useState(false);
  const [input, setInput] = useState("");
  const [isListening, setIsListening] = useState(false);
  const [micDenied, setMicDenied] = useState(false);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);

  const latestWithAlts = [...messages]
    .reverse()
    .find((m) => m.alternatives && m.alternatives.length > 0);

  const scopeChipLabel = pinnedItem
    ? `@${formatZoneLabel(pinnedItem.zone_id)} · ${pinnedItem.category}`
    : pinnedZone
    ? `@${formatZoneLabel(pinnedZone.zone_id)}`
    : null;

  const startMic = () => {
    const win = window as unknown as {
      SpeechRecognition?: new () => SpeechRecognitionLike;
      webkitSpeechRecognition?: new () => SpeechRecognitionLike;
    };
    const Rec = win.SpeechRecognition || win.webkitSpeechRecognition;
    if (!Rec) {
      setMicDenied(true);
      return;
    }
    try {
      const rec = new Rec();
      rec.continuous = false;
      rec.interimResults = true;
      rec.lang = "en-US";
      rec.onresult = (e) => {
        let txt = "";
        for (let i = 0; i < e.results.length; i++) {
          txt += e.results[i][0].transcript;
        }
        setInput(txt.trim());
      };
      rec.onerror = () => {
        setMicDenied(true);
        setIsListening(false);
      };
      rec.onend = () => setIsListening(false);
      recognitionRef.current = rec;
      rec.start();
      setIsListening(true);
      setExpanded(true);
    } catch {
      setMicDenied(true);
    }
  };

  const stopMic = () => {
    recognitionRef.current?.stop();
    setIsListening(false);
  };

  const handleSubmit = async (e?: React.FormEvent, overrideText?: string) => {
    e?.preventDefault();
    const text = (overrideText ?? input).trim();
    if (!text || isSending) return;
    setInput("");
    setExpanded(true);
    await onSendUtterance(text);
  };

  return (
    <div
      className={`absolute bottom-3 left-3 right-3 z-30 rounded-2xl bg-at-card/95 backdrop-blur-md border border-at-border shadow-xl transition-all duration-300 flex flex-col ${
        expanded ? "max-h-[44%]" : ""
      }`}
    >
      {expanded && (
        <div className="p-3 border-b border-at-border overflow-y-auto space-y-2.5">
          <div className="flex items-center justify-between">
            <span className="inline-flex items-center gap-1.5 text-[11px] font-mono uppercase tracking-wider text-at-cyan">
              <Sparkles className="h-3.5 w-3.5" />
              Conversational Spatial Thread
            </span>
            <button
              type="button"
              onClick={() => setExpanded(false)}
              className="p-1 rounded-md hover:bg-at-bg text-at-muted cursor-pointer"
            >
              <ChevronDown className="h-4 w-4" />
            </button>
          </div>

          {messages.length === 0 && (
            <div className="flex flex-wrap gap-1.5">
              {QUICK_CHIPS.map((chip) => (
                <button
                  key={chip}
                  type="button"
                  onClick={() => handleSubmit(undefined, chip)}
                  className="px-2.5 py-1 rounded-full bg-at-bg border border-at-border hover:border-at-cyan text-[11px] text-at-muted hover:text-at-ink transition-colors cursor-pointer"
                >
                  &ldquo;{chip}&rdquo;
                </button>
              ))}
            </div>
          )}

          {messages.length > 0 && (
            <div className="space-y-1.5">
              {messages.slice(-2).map((m) => (
                <div
                  key={m.id}
                  className={`text-xs leading-relaxed ${
                    m.role === "user"
                      ? "text-at-muted font-mono text-[11px]"
                      : "text-at-ink"
                  }`}
                >
                  {m.role === "user" ? `You: "${m.text}"` : m.text}
                </div>
              ))}
            </div>
          )}

          {latestWithAlts?.alternatives && (
            <div className="flex gap-2.5 overflow-x-auto pb-1">
              {latestWithAlts.alternatives.map((alt) => (
                <div
                  key={alt.sku_id}
                  className={`w-60 shrink-0 rounded-xl p-2.5 bg-at-bg border flex flex-col justify-between gap-2 ${
                    alt.hook_blocked
                      ? "border-at-coral/70 bg-at-coral/5"
                      : "border-at-border hover:border-at-cyan"
                  }`}
                >
                  <div className="flex gap-2.5">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={alt.image_url}
                      alt={alt.title}
                      className="h-12 w-12 rounded-lg object-cover border border-at-border shrink-0"
                    />
                    <div className="min-w-0">
                      <p className="text-[11px] font-semibold text-at-ink line-clamp-2 leading-tight">
                        {alt.title}
                      </p>
                      <p className="text-[10px] font-mono tabular-nums-strict text-at-muted mt-0.5">
                        ${alt.price_usd.toFixed(2)}{" "}
                        <span
                          className={
                            alt.price_delta_usd <= 0
                              ? "text-at-emerald"
                              : "text-at-notice"
                          }
                        >
                          ({alt.price_delta_usd <= 0 ? "" : "+"}$
                          {alt.price_delta_usd.toFixed(0)})
                        </span>
                      </p>
                    </div>
                  </div>

                  {alt.hook_blocked ? (
                    <div
                      title={alt.block_reason || undefined}
                      className="px-2 py-1 rounded-md bg-at-coral/15 border border-at-coral/55 text-[10px] font-mono text-at-coral flex items-start gap-1"
                    >
                      <ShieldAlert className="h-3 w-3 shrink-0 mt-0.5" />
                      <span className="leading-tight">
                        {alt.block_reason ||
                          `Blocked by hooks.json (${alt.fit_delta_label})`}
                      </span>
                    </div>
                  ) : (
                    <div className="flex items-center justify-between gap-1.5">
                      <span className="text-[10px] font-mono text-at-emerald">
                        {alt.fit_delta_label}
                      </span>
                      <button
                        type="button"
                        disabled={isSwapping}
                        onClick={() => onSelectAlternative(alt)}
                        className="px-2.5 py-1 rounded-full bg-at-cyan hover:opacity-95 text-[#0C0D10] text-[10px] font-semibold disabled:opacity-50 cursor-pointer"
                      >
                        {isSwapping ? "Swapping…" : "Surgical Swap"}
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Spacious Single Horizontal Bar with Live Audio Waveform */}
      <form onSubmit={handleSubmit} className="p-3">
        <div className="flex items-center gap-2.5 rounded-full bg-at-bg border border-at-border px-2.5 py-2 shadow-xs">
          <button
            type="button"
            onClick={() => setExpanded((e) => !e)}
            className="h-10 w-10 rounded-full bg-at-card border border-at-border flex items-center justify-center text-at-muted hover:text-at-ink shrink-0 cursor-pointer"
            title="Toggle spatial thread"
          >
            {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronUp className="h-4 w-4" />}
          </button>

          <button
            type="button"
            onMouseDown={startMic}
            onMouseUp={stopMic}
            onMouseLeave={() => isListening && stopMic()}
            onTouchStart={startMic}
            onTouchEnd={stopMic}
            className={`h-10 px-3.5 rounded-full flex items-center gap-1.5 border transition-colors shrink-0 cursor-pointer ${
              isListening
                ? "bg-at-cyan/15 border-at-cyan text-at-cyan"
                : "bg-at-card border-at-border text-at-cyan hover:border-at-cyan"
            }`}
            title="Hold to speak"
          >
            {micDenied ? (
              <MicOff className="h-4 w-4 text-at-notice" />
            ) : isListening ? (
              <span className="flex items-center gap-0.5 h-4 px-0.5">
                {[0, 1, 2].map((bar) => (
                  <span
                    key={bar}
                    className="w-0.5 h-full bg-at-cyan rounded-full animate-datum-wave"
                    style={{ animationDelay: `${bar * 120}ms` }}
                  />
                ))}
              </span>
            ) : (
              <Mic className="h-4 w-4" />
            )}
            <span className="hidden sm:inline text-xs font-medium">
              {isListening ? "Listening…" : "Speak"}
            </span>
          </button>

          {scopeChipLabel && (
            <span className="inline-flex items-center gap-1 px-3 py-1.5 rounded-full bg-at-cyan/12 border border-at-cyan/40 text-xs font-mono text-at-cyan shrink-0">
              {scopeChipLabel}
              <button
                type="button"
                onClick={onClearPin}
                className="hover:opacity-75 cursor-pointer"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </span>
          )}

          <input
            type="text"
            value={input}
            onFocus={() => setExpanded(true)}
            onChange={(e) => setInput(e.target.value)}
            placeholder='Ask to swap any item (e.g., "Swap chair for warmer cream under $180")'
            className="flex-1 bg-transparent text-sm sm:text-base text-at-ink placeholder:text-at-muted focus:outline-none min-w-0 px-1"
          />

          <button
            type="submit"
            disabled={isSending || !input.trim()}
            className="h-10 px-4 rounded-full bg-at-cyan hover:opacity-95 disabled:opacity-40 text-[#0C0D10] text-xs sm:text-sm font-semibold inline-flex items-center gap-1.5 shrink-0 cursor-pointer"
          >
            {isSending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <>
                <span>Send</span>
                <Send className="h-3.5 w-3.5" />
              </>
            )}
          </button>
        </div>
      </form>
    </div>
  );
}
