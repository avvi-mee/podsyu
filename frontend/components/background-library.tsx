"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { Film, Loader2, Search, Sparkles, Star, Trash2, Upload, Wand2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Empty, JobRow } from "@/components/common";
import { api, API, fmtTime, type BackgroundMedia } from "@/lib/api";
import { useLive, useLiveRefresh } from "@/lib/live";
import { cn } from "@/lib/utils";

type MediaList = { items: BackgroundMedia[]; categories: string[]; presets: Record<string, { title: string; category: string }> };

/** Background footage library (upload, generate original loops, import licensed stock). Used by the Media Library
 * and the ASMR Stories Factory (where `onPick` lets you choose the footage for the current story). */
export function BackgroundLibrary({ onPick, pickedId, onItems }: {
  onPick?: (id: number | null) => void; pickedId?: number | null; onItems?: (items: BackgroundMedia[]) => void;
} = {}) {
  const [data, setData] = useState<MediaList | null>(null);
  const [cat, setCat] = useState("satisfying");
  const [preset, setPreset] = useState("neon_plasma");
  const [busy, setBusy] = useState(false);
  const [q, setQ] = useState("");
  const [results, setResults] = useState<{ id: number; image: string; duration: number; creator: string; file: string; url: string }[] | null>(null);
  const { jobs } = useLive();
  const mediaJobs = jobs.filter((j) => j.type === "media");
  const load = useCallback(
    () => api<MediaList>("/api/media").then((d) => { setData(d); onItems?.(d.items); }).catch((e) => toast.error(e.message)),
    [onItems],
  );
  useEffect(() => {
    load();
  }, [load]);
  useLiveRefresh(load, (j) => j.type === "media");

  const upload = async (files: FileList) => {
    setBusy(true);
    try {
      for (const f of Array.from(files)) {
        await api(`/api/media/upload?filename=${encodeURIComponent(f.name)}&category=${cat}`, {
          method: "POST", body: f, headers: { "Content-Type": "application/octet-stream" },
        });
      }
      toast.success("Footage added");
      load();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const act = (p: Promise<unknown>, ok: string) => p.then(() => { toast.success(ok); load(); }).catch((e) => toast.error(e.message));

  return (
    <div className="space-y-4">
      <div className="grid lg:grid-cols-3 gap-4">
        <Card>
          <CardHeader><CardTitle className="flex items-center gap-2"><Upload className="size-4 text-primary" /> My own footage</CardTitle></CardHeader>
          <CardContent className="space-y-3 text-sm">
            <p className="text-muted-foreground">Gameplay you recorded, satisfying clips you filmed… MP4, MOV, MKV, WEBM.</p>
            <NativeSelect className="w-full" value={cat} onChange={(e) => setCat(e.target.value)} aria-label="Category">
              {data?.categories.map((c) => <NativeSelectOption key={c} value={c}>{c}</NativeSelectOption>)}
            </NativeSelect>
            <label className="inline-flex">
              <input type="file" multiple accept=".mp4,.mov,.mkv,.webm,video/*" className="sr-only" onChange={(e) => e.target.files?.length && upload(e.target.files)} />
              <span className="inline-flex h-8 items-center gap-2 rounded-lg bg-primary px-3 font-medium text-primary-foreground cursor-pointer">
                {busy ? <Loader2 className="size-4 animate-spin" /> : <Upload className="size-4" />} Upload videos
              </span>
            </label>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="flex items-center gap-2"><Wand2 className="size-4 text-primary" /> Generate original loop</CardTitle></CardHeader>
          <CardContent className="space-y-3 text-sm">
            <p className="text-muted-foreground">Rendered locally by FFmpeg - 100% original, no licence needed.</p>
            <NativeSelect className="w-full" value={preset} onChange={(e) => setPreset(e.target.value)} aria-label="Preset">
              {data && Object.entries(data.presets).map(([k, v]) => <NativeSelectOption key={k} value={k}>{v.title} ({v.category})</NativeSelectOption>)}
            </NativeSelect>
            <Button onClick={() => act(api("/api/media/generate", { method: "POST", json: { preset, seconds: 75 } }), "Generating footage...")}>
              <Sparkles /> Generate 75 s loop
            </Button>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="flex items-center gap-2"><Search className="size-4 text-primary" /> Licensed stock (Pexels)</CardTitle></CardHeader>
          <CardContent className="space-y-3 text-sm">
            <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); api<typeof results>(`/api/media/pexels/search?q=${encodeURIComponent(q)}`).then(setResults).catch((er) => toast.error(er.message)); }}>
              <Input placeholder="slime, ocean waves, cooking…" value={q} onChange={(e) => setQ(e.target.value)} />
              <Button type="submit" disabled={!q.trim()}><Search /></Button>
            </form>
            <p className="text-xs text-muted-foreground">Free Pexels licence; creator and licence are saved. Needs a free API key in <Link className="text-primary underline" href="/settings">Settings</Link>.</p>
          </CardContent>
        </Card>
      </div>
      {mediaJobs.slice(0, 3).map((j) => <JobRow key={j.id} job={j} showLabel={false} />)}
      {results && (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between"><CardTitle>Pexels results</CardTitle><Button size="sm" variant="ghost" onClick={() => setResults(null)}>Close</Button></CardHeader>
          <CardContent className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3">
            {results.length === 0 && <p className="text-sm text-muted-foreground">No portrait videos found.</p>}
            {results.map((r) => (
              <div key={r.id} className="space-y-1.5">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={r.image} alt="" className="aspect-[9/16] w-full rounded-lg object-cover bg-muted" />
                <p className="text-xs text-muted-foreground truncate">{fmtTime(r.duration)} · {r.creator}</p>
                <Button size="xs" className="w-full" onClick={() => act(api("/api/media/pexels/import", { method: "POST", json: { item: r, category: cat } }), "Importing...")}>Import as {cat}</Button>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
      {data?.items.length === 0 && <Empty icon={Film} title="No background videos yet">Upload, generate or import one above.</Empty>}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        {data?.items.map((m) => (
          <Card key={m.id} className={cn("p-0 gap-0 overflow-hidden", pickedId === m.id && "ring-2 ring-primary")}>
            <video src={`${API}/api/media/${m.id}/file`} poster={`${API}/api/media/${m.id}/thumbnail`} muted loop playsInline preload="none"
              className="aspect-[9/16] w-full object-cover bg-muted" onMouseEnter={(e) => e.currentTarget.play().catch(() => {})} onMouseLeave={(e) => e.currentTarget.pause()} />
            <div className="p-2.5 space-y-1.5">
              <div className="flex items-center gap-1">
                <p className="text-xs font-medium truncate flex-1" title={m.title}>{m.title}</p>
                <button aria-label="Favourite" onClick={() => act(api(`/api/media/${m.id}`, { method: "PATCH", json: { favourite: !m.favourite } }), m.favourite ? "Unstarred" : "Favourited")}>
                  <Star className={cn("size-3.5", m.favourite ? "fill-primary text-primary" : "text-muted-foreground")} />
                </button>
                <button aria-label="Delete" onClick={() => confirm(`Delete "${m.title}"?`) && act(api(`/api/media/${m.id}`, { method: "DELETE" }), "Deleted")}>
                  <Trash2 className="size-3.5 text-muted-foreground hover:text-red-400" />
                </button>
              </div>
              <NativeSelect size="sm" className="w-full" value={m.category} onChange={(e) => act(api(`/api/media/${m.id}`, { method: "PATCH", json: { category: e.target.value } }), "Category updated")} aria-label="Category">
                {data.categories.map((c) => <NativeSelectOption key={c} value={c}>{c}</NativeSelectOption>)}
              </NativeSelect>
              <p className="text-[11px] text-muted-foreground truncate" title={m.license ?? ""}>{fmtTime(m.duration)} · {m.source}{m.creator ? ` · ${m.creator}` : ""}</p>
              {onPick && (
                <Button size="xs" className="w-full" variant={pickedId === m.id ? "default" : "outline"} onClick={() => onPick(pickedId === m.id ? null : m.id)}>
                  {pickedId === m.id ? "✓ Using for this story" : "Use for this story"}
                </Button>
              )}
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}

