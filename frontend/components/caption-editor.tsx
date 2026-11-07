"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Slider } from "@/components/ui/slider";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { api, type CaptionStyle, type Options } from "@/lib/api";

export function presetStyle(meta: Options, key: string): CaptionStyle {
  return { ...meta.presets[key], preset: key };
}

/** Live preview: the backend renders a real frame with these captions burned in, exactly like the final video. */
export function CaptionPreview({ style, shortId, className }: { style: CaptionStyle; shortId?: number; className?: string }) {
  const [src, setSrc] = useState<string>();
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const key = JSON.stringify(style) + shortId;

  useEffect(() => {
    let url: string | undefined;
    let cancelled = false;
    const t = setTimeout(async () => {
      setLoading(true);
      try {
        const blob = await api<Blob>("/api/captions/preview", { method: "POST", json: { style, short_id: shortId } });
        if (cancelled) return;
        url = URL.createObjectURL(blob);
        setSrc(url);
        setErr("");
      } catch (e) {
        if (!cancelled) setErr((e as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, 500);
    return () => {
      cancelled = true;
      clearTimeout(t);
      if (url) URL.revokeObjectURL(url);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return (
    <div className={`relative aspect-[9/16] rounded-xl overflow-hidden bg-muted border ${className ?? ""}`}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      {src && <img src={src} alt="Caption preview" className="size-full object-cover" />}
      {loading && <Loader2 className="absolute top-2 right-2 size-4 animate-spin text-white drop-shadow" />}
      {err && <p className="absolute inset-x-2 bottom-2 text-xs text-red-300 bg-black/70 rounded p-2">{err}</p>}
    </div>
  );
}

export function CaptionEditor({ style, onChange, meta }: { style: CaptionStyle; onChange: (s: CaptionStyle) => void; meta: Options }) {
  const set = <K extends keyof CaptionStyle>(k: K, v: CaptionStyle[K]) => onChange({ ...style, [k]: v });
  const num = (v: number | readonly number[]) => (Array.isArray(v) ? v[0] : (v as number));

  return (
    <div className="space-y-4">
      <Row label="Preset">
        <NativeSelect className="w-full" value={style.preset ?? ""} onChange={(e) => onChange(presetStyle(meta, e.target.value))}>
          {Object.entries(meta.presets).map(([k, p]) => <NativeSelectOption key={k} value={k}>{p.name}</NativeSelectOption>)}
        </NativeSelect>
      </Row>
      <div className="grid grid-cols-2 gap-3">
        <Row label="Font">
          <NativeSelect className="w-full" value={style.font} onChange={(e) => set("font", e.target.value)}>
            {[...new Set([style.font, ...meta.fonts])].map((f) => <NativeSelectOption key={f} value={f}>{f}</NativeSelectOption>)}
          </NativeSelect>
        </Row>
        <Row label="Position">
          <NativeSelect className="w-full" value={style.position} onChange={(e) => set("position", e.target.value)}>
            {meta.positions.map((p) => <NativeSelectOption key={p} value={p}>{p}</NativeSelectOption>)}
          </NativeSelect>
        </Row>
      </div>
      <Row label={`Font size · ${style.font_size}px`}>
        <Slider min={24} max={160} value={[style.font_size]} onValueChange={(v) => set("font_size", num(v))} />
      </Row>
      <div className="grid grid-cols-3 gap-3">
        <Color label="Text" value={style.text_color} onChange={(v) => set("text_color", v)} />
        <Color label="Highlight" value={style.highlight_color} onChange={(v) => set("highlight_color", v)} />
        <Color label="Outline" value={style.outline_color} onChange={(v) => set("outline_color", v)} />
      </div>
      <Row label={`Outline thickness · ${style.outline_width}`}>
        <Slider min={0} max={15} step={0.5} value={[style.outline_width]} onValueChange={(v) => set("outline_width", num(v))} />
      </Row>
      <Row label={`Shadow · ${style.shadow}`}>
        <Slider min={0} max={10} step={0.5} value={[style.shadow]} onValueChange={(v) => set("shadow", num(v))} />
      </Row>
      <Row label={`Words per line · ${style.words_per_line} (max 2 lines)`}>
        <Slider min={1} max={8} value={[style.words_per_line]} onValueChange={(v) => set("words_per_line", num(v))} />
      </Row>
      <div className="grid grid-cols-2 gap-3">
        <Row label="Animation">
          <NativeSelect className="w-full" value={style.animation} onChange={(e) => set("animation", e.target.value)}>
            {meta.animations.map((a) => <NativeSelectOption key={a} value={a}>{a}</NativeSelectOption>)}
          </NativeSelect>
        </Row>
        <Row label="Background">
          <NativeSelect className="w-full" value={style.background} onChange={(e) => set("background", e.target.value)}>
            <NativeSelectOption value="none">None (outline/shadow)</NativeSelectOption>
            <NativeSelectOption value="box">Box</NativeSelectOption>
          </NativeSelect>
        </Row>
      </div>
      {style.background === "box" && <Color label="Box colour" value={style.background_color} onChange={(v) => set("background_color", v)} />}
      <div className="grid grid-cols-2 gap-x-4 gap-y-2">
        <Toggle label="Highlight spoken word" checked={style.highlight} onChange={(v) => set("highlight", v)} />
        <Toggle label="UPPERCASE" checked={style.uppercase} onChange={(v) => set("uppercase", v)} />
        <Toggle label="Bold" checked={style.bold} onChange={(v) => set("bold", v)} />
        <Toggle label="Italic" checked={style.italic} onChange={(v) => set("italic", v)} />
      </div>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      {children}
    </div>
  );
}

function Color({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <Row label={label}>
      <div className="flex items-center gap-2">
        <input type="color" value={value} onChange={(e) => onChange(e.target.value.toUpperCase())} className="size-8 rounded border bg-transparent cursor-pointer" aria-label={`${label} colour`} />
        <Input value={value} onChange={(e) => /^#[0-9a-fA-F]{0,6}$/.test(e.target.value) && onChange(e.target.value.toUpperCase())} className="h-8 font-mono text-xs" />
      </div>
    </Row>
  );
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-center justify-between gap-2 text-sm cursor-pointer">
      {label}
      <Switch checked={checked} onCheckedChange={onChange} />
    </label>
  );
}
