"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Film, Info, Loader2, Music, Save, Scissors, Star, Trash2, Upload } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Empty, PageHeader } from "@/components/common";
import { BackgroundLibrary } from "@/components/background-library";
import { api, API, fmtTime, type MusicTrack } from "@/lib/api";
import { cn } from "@/lib/utils";

const MUSIC_CATS = ["funny", "suspense", "dark", "horror", "relaxing", "emotional", "cinematic", "mysterious", "inspirational"];

export default function MediaLibraryPage() {
  return (
    <>
      <PageHeader title="Media Library" description="Background footage for story shorts and the BGM library shared by every engine." />
      <Tabs defaultValue="video">
        <TabsList className="mb-4">
          <TabsTrigger value="video"><Film className="size-4" /> Background videos</TabsTrigger>
          <TabsTrigger value="music"><Music className="size-4" /> BGM library</TabsTrigger>
        </TabsList>
        <TabsContent value="video"><BackgroundLibrary /></TabsContent>
        <TabsContent value="music"><BgmLibrary /></TabsContent>
      </Tabs>
    </>
  );
}

// ---------------- BGM library ----------------

function BgmLibrary() {
  const [tracks, setTracks] = useState<MusicTrack[] | null>(null);
  const [filter, setFilter] = useState("");
  const [uploading, setUploading] = useState(false);
  const [license, setLicense] = useState("");
  const load = useCallback(() => api<MusicTrack[]>("/api/music").then(setTracks).catch((e) => toast.error(e.message)), []);
  useEffect(() => {
    load();
  }, [load]);

  const upload = async (files: FileList) => {
    setUploading(true);
    try {
      for (const f of Array.from(files)) {
        await api(`/api/music/upload?filename=${encodeURIComponent(f.name)}&license=${encodeURIComponent(license)}`, {
          method: "POST", body: f, headers: { "Content-Type": "application/octet-stream" },
        });
      }
      toast.success("Added to the BGM library");
      load();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setUploading(false);
    }
  };
  const full = (tracks ?? []).filter((t) => t.parent_id === null && (!filter || (filter === "fav" ? t.favourite : t.category === filter)));

  return (
    <div className="space-y-4">
      <div className="flex gap-2 rounded-xl border border-sky-500/30 bg-sky-500/10 p-3 text-sm">
        <Info className="size-4 mt-0.5 shrink-0 text-sky-300" />
        <span>Only add music you own or are licensed to use (e.g. YouTube Studio → Audio Library, Creative Commons). Credit lines are added to YouTube descriptions automatically. Music always plays quieter than speech and ducks under it.</span>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <NativeSelect size="sm" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter">
          <NativeSelectOption value="">All categories</NativeSelectOption>
          <NativeSelectOption value="fav">★ Favourites</NativeSelectOption>
          {MUSIC_CATS.map((c) => <NativeSelectOption key={c} value={c}>{c}</NativeSelectOption>)}
        </NativeSelect>
        <Input className="w-56 h-7" placeholder="Licence for new uploads (e.g. own)" value={license} onChange={(e) => setLicense(e.target.value)} />
        <label className="ml-auto">
          <input type="file" multiple accept="audio/*,video/*,.mp3,.wav,.m4a,.aac,.ogg,.flac,.mp4,.mov,.mkv,.webm" className="sr-only" onChange={(e) => e.target.files?.length && upload(e.target.files)} />
          <span className="inline-flex h-8 items-center gap-2 rounded-lg bg-primary px-3 text-sm font-medium text-primary-foreground cursor-pointer">
            {uploading ? <Loader2 className="size-4 animate-spin" /> : <Upload className="size-4" />} Add audio / extract from video
          </span>
        </label>
      </div>
      {full.length === 0 && tracks && <Empty icon={Music} title="No tracks here">Add music above, or drop files into the data\music folder.</Empty>}
      {full.map((t) => <TrackCard key={t.id} track={t} snippets={(tracks ?? []).filter((s) => s.parent_id === t.id)} onChanged={load} />)}
    </div>
  );
}

function TrackCard({ track, snippets, onChanged }: { track: MusicTrack; snippets: MusicTrack[]; onChanged: () => void }) {
  const [form, setForm] = useState({ title: track.title, credit: track.credit, license: track.license ?? "", source_url: track.source_url ?? "" });
  const [busy, setBusy] = useState(false);
  const dirty = form.title !== track.title || form.credit !== track.credit || form.license !== (track.license ?? "") || form.source_url !== (track.source_url ?? "");
  const patch = (json: object, ok: string) => api(`/api/music/${track.id}`, { method: "PATCH", json }).then(() => { toast.success(ok); onChanged(); }).catch((e) => toast.error(e.message));
  const makeSnippets = async () => {
    setBusy(true);
    try {
      const r = await api<MusicTrack[]>(`/api/music/${track.id}/snippets`, { method: "POST" });
      toast.success(`Found the catchiest part - ${r.length} snippet(s) saved`);
      onChanged();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader className="flex flex-row items-center gap-3">
        <div className="size-9 rounded-lg bg-primary/15 grid place-items-center shrink-0"><Music className="size-4 text-primary" /></div>
        <div className="min-w-0 flex-1">
          <CardTitle className="truncate">{track.title}</CardTitle>
          <p className="text-xs text-muted-foreground">{fmtTime(track.duration)} · {track.license || "licence not set"}</p>
        </div>
        <NativeSelect size="sm" value={track.category ?? ""} onChange={(e) => patch({ category: e.target.value || null }, "Category saved")} aria-label="Category">
          <NativeSelectOption value="">No category</NativeSelectOption>
          {MUSIC_CATS.map((c) => <NativeSelectOption key={c} value={c}>{c}</NativeSelectOption>)}
        </NativeSelect>
        <Button size="icon-sm" variant="ghost" aria-label="Favourite" onClick={() => patch({ favourite: !track.favourite }, track.favourite ? "Unstarred" : "Favourited")}>
          <Star className={cn(track.favourite && "fill-primary text-primary")} />
        </Button>
        <Button size="icon-sm" variant="ghost" aria-label={`Delete ${track.title}`} onClick={() => confirm(`Delete "${track.title}" and its snippets?`) && api(`/api/music/${track.id}`, { method: "DELETE" }).then(() => { toast.success("Deleted"); onChanged(); }).catch((e) => toast.error(e.message))}>
          <Trash2 />
        </Button>
      </CardHeader>
      <CardContent className="space-y-3">
        <audio controls preload="none" src={`${API}/api/music/${track.id}/file`} className="w-full h-9" />
        <div className="grid md:grid-cols-2 gap-2">
          <Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} aria-label="Title" />
          <Input value={form.license} placeholder="Licence (e.g. CC BY 4.0)" onChange={(e) => setForm({ ...form, license: e.target.value })} aria-label="Licence" />
          <Input value={form.credit} placeholder="Credit line (added to YouTube descriptions)" onChange={(e) => setForm({ ...form, credit: e.target.value })} aria-label="Credit" />
          <Input value={form.source_url} placeholder="Source URL" onChange={(e) => setForm({ ...form, source_url: e.target.value })} aria-label="Source" />
        </div>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" disabled={!dirty} onClick={() => patch(form, "Saved")}><Save /> Save</Button>
          <Button size="sm" variant="outline" disabled={busy || track.duration < 16} onClick={makeSnippets}>
            {busy ? <Loader2 className="animate-spin" /> : <Scissors />} {snippets.length ? "Re-detect catchy snippets" : "Find catchy snippets (15/20/30 s)"}
          </Button>
        </div>
        {snippets.length > 0 && (
          <div className="space-y-2 rounded-lg border p-3">
            <p className="text-xs text-muted-foreground">Snippets of the catchiest part. Pick one for a short, and it loops seamlessly to the video length.</p>
            {snippets.map((s) => <SnippetRow key={s.id} snip={s} parentDuration={track.duration} onChanged={onChanged} />)}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function SnippetRow({ snip, parentDuration, onChanged }: { snip: MusicTrack; parentDuration: number; onChanged: () => void }) {
  const [start, setStart] = useState(snip.clip_start ?? 0);
  const [len, setLen] = useState(Math.round(snip.duration));
  const [v, setV] = useState(0);
  const save = () =>
    api(`/api/music/${snip.id}`, { method: "PATCH", json: { clip_start: start, length: len } })
      .then(() => { toast.success("Snippet trimmed"); setV((x) => x + 1); onChanged(); })
      .catch((e) => toast.error(e.message));
  return (
    <div className="grid md:grid-cols-[1fr_auto] gap-2 items-center">
      <div className="min-w-0">
        <p className="text-sm truncate">{snip.title}</p>
        <audio key={v} controls preload="none" src={`${API}/api/music/${snip.id}/file?v=${v}`} className="w-full h-8" />
      </div>
      <div className="flex items-center gap-1.5">
        <Input type="number" step={0.5} min={0} max={Math.max(0, parentDuration - len)} value={start} onChange={(e) => setStart(+e.target.value)} className="w-20 h-7" aria-label="Start (s)" />
        <NativeSelect size="sm" value={len} onChange={(e) => setLen(+e.target.value)} aria-label="Length">
          {[15, 20, 25, 30].map((l) => <NativeSelectOption key={l} value={l}>{l}s</NativeSelectOption>)}
        </NativeSelect>
        <Button size="xs" variant="outline" onClick={save}><Scissors /> Trim</Button>
        <Button size="icon-xs" variant="ghost" aria-label="Delete snippet" onClick={() => api(`/api/music/${snip.id}`, { method: "DELETE" }).then(() => { toast.success("Snippet deleted"); onChanged(); }).catch((e) => toast.error(e.message))}><Trash2 /></Button>
      </div>
    </div>
  );
}
