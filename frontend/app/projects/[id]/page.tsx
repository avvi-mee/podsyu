"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { toast } from "sonner";
import {
  Check, CheckCircle2, Circle, Clapperboard, FileText, HardDrive, Loader2, Music, Palette, RefreshCw, RotateCcw, Sparkles, Trash2, Upload, X,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Empty, JobRow, StatusBadge } from "@/components/common";
import { ShortCard } from "@/components/short-card";
import { api, API, fmtDate, fmtTime, MUSIC_LEVELS, type MusicTrack, type Options, type ProjectDetail } from "@/lib/api";
import { useLive, useLiveRefresh } from "@/lib/live";
import { cn } from "@/lib/utils";

const STEPS = [
  ["downloading", "Import video"], ["validating", "Validate"], ["extracting audio", "Extract audio"], ["transcribing", "Transcribe"],
  ["finding best moments", "Find moments"], ["writing titles", "Titles & hashtags"], ["rendering", "Render shorts"],
] as const;

// Suspense: the project id comes from the URL at runtime.
export default function ProjectPage() {
  return (
    <Suspense>
      <ProjectView />
    </Suspense>
  );
}

function ProjectView() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [p, setP] = useState<ProjectDetail | null>(null);
  const [meta, setMeta] = useState<Options | null>(null);
  const [transcript, setTranscript] = useState<{ start: number; text: string }[] | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [opts, setOpts] = useState({ min_duration: 30, max_duration: 90, num_shorts: 5, category: "any", strategy: "balanced" });
  const [preset, setPreset] = useState("hormozi");
  const [tracks, setTracks] = useState<MusicTrack[]>([]);
  const [music, setMusic] = useState({ track: "none", volume: 0.1 });
  const { jobs } = useLive();

  const load = useCallback(
    () =>
      api<ProjectDetail>(`/api/projects/${id}`)
        .then((d) => {
          setP(d);
          setOpts((o) => ({ ...o, ...(d.options as typeof o) }));
          if (d.caption_style?.preset) setPreset(d.caption_style.preset);
          setMusic({ track: d.music ?? "none", volume: d.music_volume ?? 0.1 });
        })
        .catch((e) => toast.error(e.message)),
    [id],
  );
  useEffect(() => {
    load();
    api<Options>("/api/meta/options").then(setMeta).catch(() => {});
    api<MusicTrack[]>("/api/music").then(setTracks).catch(() => {});
  }, [load]);
  useLiveRefresh(load, (j) => j.project_id === Number(id));

  const liveJob = jobs.find((j) => j.project_id === Number(id) && ["process", "creator_analyze", "asmr", "cutting"].includes(j.type) && (j.status === "running" || j.status === "queued"));
  const stepIdx = liveJob ? STEPS.findIndex(([k]) => liveJob.stage.startsWith(k)) : -1;

  const run = async (body: object, ok: string) => {
    try {
      await api(`/api/projects/${id}/process`, { method: "POST", json: body });
      toast.success(ok);
      load();
    } catch (e) {
      toast.error((e as Error).message);
    }
  };
  const bulk = async (action: string) => {
    if (action === "delete" && !confirm(`Delete ${selected.size} short(s)?`)) return;
    try {
      await api("/api/shorts/bulk", { method: "POST", json: { ids: [...selected], action } });
      toast.success(`${selected.size} short(s) updated`);
      setSelected(new Set());
      load();
    } catch (e) {
      toast.error((e as Error).message);
    }
  };
  const applyMusic = async () => {
    try {
      const r = await api<{ queued: number }>(`/api/projects/${id}/music`, {
        method: "PUT", json: { music: music.track, music_volume: music.track === "none" ? null : music.volume },
      });
      toast.success(`${music.track === "none" ? "Music removed" : "Music applied"} - re-rendering ${r.queued} short(s)`);
      load();
    } catch (e) {
      toast.error((e as Error).message);
    }
  };
  const applyPreset = async () => {
    if (!meta) return;
    try {
      const r = await api<{ queued: number }>(`/api/projects/${id}/caption-style`, { method: "PUT", json: { style: { preset } } });
      toast.success(`Applied ${meta.presets[preset].name} - re-rendering ${r.queued} short(s)`);
      load();
    } catch (e) {
      toast.error((e as Error).message);
    }
  };
  const loadTranscript = () =>
    !transcript && api<{ segments: { start: number; text: string }[] }>(`/api/projects/${id}/transcript`).then((t) => setTranscript(t.segments)).catch((e) => toast.error(e.message));
  const delSource = async () => {
    if (!confirm("Delete the source video? Finished shorts and the transcript are kept, but shorts can no longer be re-rendered.")) return;
    try {
      await api(`/api/projects/${id}/delete-source`, { method: "POST" });
      toast.success("Source video deleted");
      load();
    } catch (e) {
      toast.error((e as Error).message);
    }
  };
  const delProject = async () => {
    if (!confirm("Delete this project, all shorts and files?")) return;
    try {
      await api(`/api/projects/${id}`, { method: "DELETE" });
      router.push("/projects");
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  const [sort, setSort] = useState("score");
  const shorts = useMemo(() => {
    const list = [...(p?.shorts ?? [])];
    const humor = (x: (typeof list)[number]) => Number(x.details?.scores?.humor ?? 0);
    const by: Record<string, (a: (typeof list)[number], b: (typeof list)[number]) => number> = {
      score: (a, b) => b.score - a.score, funniest: (a, b) => humor(b) - humor(a) || b.score - a.score,
      newest: (a, b) => b.start - a.start, shortest: (a, b) => a.end - a.start - (b.end - b.start),
      longest: (a, b) => b.end - b.start - (a.end - a.start),
    };
    return p?.engine === "creator" ? list.sort(by[sort]) : list;
  }, [p, sort]);
  if (!p) return <div className="grid place-items-center h-64"><Loader2 className="animate-spin text-primary" /></div>;
  const allSelected = shorts.length > 0 && selected.size === shorts.length;
  const autoDelete = Boolean((p.options as { auto_delete_source?: boolean }).auto_delete_source);
  const setAutoDelete = (v: boolean) =>
    api(`/api/projects/${id}`, { method: "PATCH", json: { auto_delete_source: v } })
      .then(() => {
        toast.success(v ? "Source video will be deleted once all shorts are rendered" : "Source video will be kept");
        load();
      })
      .catch((e) => toast.error(e.message));
  const autoDeleteSwitch = (
    <label className="flex items-center justify-between gap-3 rounded-lg border p-3 text-sm cursor-pointer">
      <span>
        Auto-delete the source video when finished
        <span className="block text-xs text-muted-foreground">
          Frees disk space after every short renders successfully (kept if any short fails).{" "}
          {p.source_type === "youtube" ? "“Re-render all” downloads it again if needed." : "Re-rendering will need the file uploaded again."}
        </span>
      </span>
      <Switch checked={autoDelete} onCheckedChange={setAutoDelete} aria-label="Auto-delete source video when finished" />
    </label>
  );

  const engine = p.engine ?? "podcast";
  const autoPlan = p.options?.autopilot as { status: string; message: string } | undefined;
  const renderSelected = () => {
    if (!p.source_available && !confirm("Only continue if you own this video or have the rights holder's permission to download and edit it.\n\nDownload the video and render the selected clips?")) return;
    api<{ queued: number }>(`/api/creators/projects/${id}/render`, { method: "POST", json: { ids: [...selected], ...(p.source_available ? {} : { authorized: true }) } })
      .then((r) => { toast.success(`Rendering ${r.queued} clip(s)`); setSelected(new Set()); load(); })
      .catch((e) => toast.error(e.message));
  };
  const reanalyze = () =>
    api(`/api/creators/projects/${id}/analyze`, { method: "POST", json: { fresh: true } })
      .then(() => { toast.success("Re-analysing..."); load(); }).catch((e) => toast.error(e.message));
  const attachFile = async (f: File) => {
    try {
      await api(`/api/projects/upload?filename=${encodeURIComponent(f.name)}&engine=creator&project_id=${id}`, {
        method: "POST", body: f, headers: { "Content-Type": "application/octet-stream" },
      });
      toast.success("Authorized video attached - running full analysis");
      reanalyze();
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  return (
    <>
      <div className="flex flex-col md:flex-row gap-5 mb-6">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={`${API}/api/projects/${p.id}/thumbnail`} alt="" className="w-full md:w-72 aspect-video rounded-xl object-cover bg-muted" onError={(e) => (e.currentTarget.style.visibility = "hidden")} />
        <div className="min-w-0 flex-1 space-y-2">
          <div className="flex items-center gap-2"><StatusBadge status={p.status} />{p.language && <span className="text-xs text-muted-foreground uppercase">{p.language}</span>}</div>
          <h1 className="text-2xl font-semibold tracking-tight leading-tight">{p.title}</h1>
          <p className="text-sm text-muted-foreground">
            {p.channel ? `${p.channel} · ` : ""}{fmtTime(p.duration)}{p.width ? ` · ${p.width}×${p.height}` : ""} · created {fmtDate(p.created_at)}
          </p>
          {p.source_url && <a href={p.source_url} target="_blank" rel="noreferrer" className="text-xs text-primary hover:underline">{p.source_url}</a>}
          {p.error && <p className="text-sm text-red-400">{p.error}</p>}
          {autoPlan && (
            <p className={cn("text-sm", autoPlan.status === "failed" ? "text-red-400" : "text-muted-foreground")}>
              <span className="font-medium text-primary">Autopilot:</span> {autoPlan.message}{" "}
              {autoPlan.status === "scheduled" && <Link href="/calendar" className="underline">Open calendar</Link>}
            </p>
          )}
          <div className="flex flex-wrap gap-2 pt-1">
            {engine === "podcast" && (p.status === "failed" || p.status === "created") && !liveJob && (
              <Button onClick={() => run({}, "Processing resumed")}><RotateCcw /> {p.status === "created" ? "Start processing" : "Retry / resume"}</Button>
            )}
            {engine === "podcast" && (
              <>
                <Button variant="outline" disabled={!!liveJob || !p.transcript_available} onClick={() => confirm("Replace unpublished shorts with a fresh AI selection?") && run({ options: opts, reanalyze: true }, "Finding new moments...")}>
                  <Sparkles /> Find new clips
                </Button>
                <Button variant="outline" disabled={!!liveJob || (!p.source_available && p.source_type !== "youtube") || !shorts.length} onClick={() => run({ rerender: true }, "Re-rendering all shorts")}>
                  <RefreshCw /> Re-render all
                </Button>
              </>
            )}
            {engine === "creator" && (
              <>
                <Button variant="outline" disabled={!!liveJob} onClick={() => confirm("Re-analyse and replace unrendered candidates?") && reanalyze()}>
                  <Sparkles /> Re-analyse
                </Button>
                {!p.source_available && (
                  <label>
                    <input type="file" accept=".mp4,.mov,.mkv,.webm,video/*" className="sr-only" onChange={(e) => e.target.files?.[0] && attachFile(e.target.files[0])} />
                    <span className="inline-flex h-8 items-center gap-2 rounded-lg border px-2.5 text-sm cursor-pointer hover:bg-muted"><Upload className="size-4" /> Upload authorized video to render</span>
                  </label>
                )}
              </>
            )}
            {engine === "asmr" && <Button variant="outline" render={<Link href="/asmr" />} nativeButton={false}><Sparkles /> Open in ASMR Stories</Button>}
            {engine === "cutting" && <Button variant="outline" render={<Link href="/cutting" />} nativeButton={false}><Sparkles /> Open in Cutting Studio</Button>}
            <Button variant="ghost" onClick={delProject}><Trash2 /> Delete project</Button>
          </div>
        </div>
      </div>

      {liveJob && (
        <Card className="mb-6">
          <CardContent className="space-y-4">
            {engine === "podcast" && <div className="flex flex-wrap gap-x-5 gap-y-2">
              {STEPS.filter(([k]) => k !== "downloading" || p.source_type === "youtube").map(([k, label]) => {
                const i = STEPS.findIndex(([x]) => x === k);
                const done = stepIdx > i, cur = stepIdx === i;
                return (
                  <div key={k} className={cn("flex items-center gap-1.5 text-sm", done ? "text-emerald-400" : cur ? "text-foreground" : "text-muted-foreground")}>
                    {done ? <CheckCircle2 className="size-4" /> : cur ? <Loader2 className="size-4 animate-spin text-primary" /> : <Circle className="size-4" />}
                    {label}
                  </div>
                );
              })}
            </div>}
            <JobRow job={liveJob} showLabel={false} />
            {engine !== "asmr" && engine !== "cutting" && autoDeleteSwitch}
          </CardContent>
        </Card>
      )}

      <Tabs defaultValue="shorts">
        <TabsList className="mb-4">
          <TabsTrigger value="shorts"><Clapperboard className="size-4" /> Shorts ({shorts.length})</TabsTrigger>
          <TabsTrigger value="transcript" onClick={loadTranscript}><FileText className="size-4" /> Transcript</TabsTrigger>
          <TabsTrigger value="settings"><Palette className="size-4" /> Settings</TabsTrigger>
          <TabsTrigger value="history">Jobs &amp; publishing</TabsTrigger>
        </TabsList>

        <TabsContent value="shorts" className="space-y-4">
          {shorts.length > 0 && (
            <div className="flex flex-wrap items-center gap-2 rounded-xl border bg-card/60 p-2">
              <Button size="sm" variant="ghost" onClick={() => setSelected(allSelected ? new Set() : new Set(shorts.map((s) => s.id)))}>
                {allSelected ? "Clear selection" : "Select all"}
              </Button>
              {selected.size > 0 && (
                <>
                  <span className="text-xs text-muted-foreground">{selected.size} selected</span>
                  {engine === "creator" && (
                    <Button size="sm" disabled={!p.source_available && p.source_type !== "youtube"} onClick={renderSelected}><Sparkles /> Render</Button>
                  )}
                  <Button size="sm" variant="outline" onClick={() => bulk("approve")}><Check className="text-emerald-400" /> Approve</Button>
                  <Button size="sm" variant="outline" onClick={() => bulk("reject")}><X className="text-red-400" /> Reject</Button>
                  <Button size="sm" variant="ghost" onClick={() => bulk("delete")}><Trash2 /> Delete</Button>
                </>
              )}
              {engine === "creator" && (
                <div className="ml-auto">
                  <NativeSelect size="sm" value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort clips">
                    <NativeSelectOption value="score">Highest score</NativeSelectOption>
                    <NativeSelectOption value="funniest">Funniest first</NativeSelectOption>
                    <NativeSelectOption value="newest">Newest timestamp</NativeSelectOption>
                    <NativeSelectOption value="shortest">Shortest</NativeSelectOption>
                    <NativeSelectOption value="longest">Longest</NativeSelectOption>
                  </NativeSelect>
                </div>
              )}
            </div>
          )}
          {shorts.length === 0 && <Empty icon={Clapperboard} title={liveJob ? "Shorts will appear here as they're generated" : "No shorts yet"} />}
          {shorts.map((s) => (
            <ShortCard key={s.id} short={{ ...s, source_available: p.source_available, publications: p.publications.filter((x) => x.short_id === s.id) }}
              meta={meta} projectStyle={p.caption_style} selected={selected.has(s.id)} engine={engine} canRender={p.source_available}
              onSelect={(v) => setSelected((cur) => { const n = new Set(cur); if (v) n.add(s.id); else n.delete(s.id); return n; })}
              onChanged={load} />
          ))}
        </TabsContent>

        <TabsContent value="transcript">
          <Card>
            <CardContent className="max-h-[70vh] overflow-y-auto space-y-2 text-sm">
              {!p.transcript_available && <p className="text-muted-foreground">Transcript not generated yet.</p>}
              {transcript?.map((s, i) => (
                <p key={i}><span className="text-xs text-primary tabular-nums mr-2">{fmtTime(s.start)}</span>{s.text}</p>
              ))}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="settings" className="grid md:grid-cols-2 gap-4">
          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2"><Palette className="size-4" /> Style for all shorts</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <NativeSelect size="sm" value={preset} onChange={(e) => setPreset(e.target.value)} aria-label="Caption preset for all shorts">
                  {meta && Object.entries(meta.presets).map(([k, s]) => <NativeSelectOption key={k} value={k}>{s.name}</NativeSelectOption>)}
                </NativeSelect>
                <Button size="sm" disabled={!shorts.length || (!p.source_available && engine !== "asmr")} onClick={applyPreset}><Palette /> Apply captions</Button>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <NativeSelect size="sm" value={music.track} onChange={(e) => setMusic({ ...music, track: e.target.value })} aria-label="Background music for all shorts">
                  <NativeSelectOption value="none">No background music</NativeSelectOption>
                  {tracks.map((t) => <NativeSelectOption key={t.id} value={String(t.id)}>{t.title}</NativeSelectOption>)}
                </NativeSelect>
                <NativeSelect size="sm" value={music.volume} disabled={music.track === "none"} onChange={(e) => setMusic({ ...music, volume: +e.target.value })} aria-label="Music volume">
                  {MUSIC_LEVELS.map((l) => <NativeSelectOption key={l.v} value={l.v}>{l.label}</NativeSelectOption>)}
                </NativeSelect>
                <Button size="sm" disabled={!shorts.length || (!p.source_available && engine !== "asmr")} onClick={applyMusic}><Music /> Apply music</Button>
              </div>
              <p className="text-xs text-muted-foreground">Re-renders every short with the chosen caption style or music.</p>
            </CardContent>
          </Card>
          {engine === "podcast" && <Card>
            <CardHeader><CardTitle>Clip selection</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <div className="grid grid-cols-3 gap-2">
                {(["min_duration", "max_duration", "num_shorts"] as const).map((k) => (
                  <div key={k} className="space-y-1">
                    <Label className="text-xs text-muted-foreground">{k === "num_shorts" ? "Shorts" : k === "min_duration" ? "Min (s)" : "Max (s)"}</Label>
                    <Input type="number" value={opts[k]} onChange={(e) => setOpts({ ...opts, [k]: +e.target.value })} />
                  </div>
                ))}
              </div>
              <NativeSelect className="w-full" value={opts.category} onChange={(e) => setOpts({ ...opts, category: e.target.value })} aria-label="Category">
                <NativeSelectOption value="any">Any category</NativeSelectOption>
                {meta?.categories.map((c) => <NativeSelectOption key={c} value={c}>{c}</NativeSelectOption>)}
              </NativeSelect>
              <NativeSelect className="w-full" value={opts.strategy} onChange={(e) => setOpts({ ...opts, strategy: e.target.value })} aria-label="Strategy">
                {meta && Object.keys(meta.strategies).map((s) => <NativeSelectOption key={s} value={s}>{s}</NativeSelectOption>)}
              </NativeSelect>
              <p className="text-xs text-muted-foreground">Used by &quot;Find new clips&quot; (re-uses the saved transcript, no re-transcription).</p>
            </CardContent>
          </Card>}
          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2"><HardDrive className="size-4" /> Storage</CardTitle></CardHeader>
            <CardContent className="space-y-3 text-sm">
              <p>Source video: {p.source_available ? <span className="text-emerald-400">kept on disk</span> : <span className="text-muted-foreground">{p.source_deleted ? "deleted" : "not downloaded yet"}</span>}</p>
              <p className="text-muted-foreground">Deleting the source frees disk space. Finished shorts, the transcript and metadata are kept, but shorts can no longer be re-rendered or re-captioned.</p>
              <Button variant="outline" disabled={!p.source_available || !!liveJob} onClick={delSource}><Trash2 /> Delete source video now</Button>
              {p.source_available && autoDeleteSwitch}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="history" className="grid md:grid-cols-2 gap-4">
          <Card>
            <CardHeader><CardTitle>Processing jobs</CardTitle></CardHeader>
            <CardContent className="space-y-2">
              {p.jobs.length === 0 && <p className="text-sm text-muted-foreground">No jobs yet.</p>}
              {p.jobs.map((j) => <JobRow key={j.id} job={jobs.find((x) => x.id === j.id) ?? j} showLabel={false} />)}
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Publishing history</CardTitle></CardHeader>
            <CardContent className="space-y-2">
              {p.publications.length === 0 && <p className="text-sm text-muted-foreground">Nothing published yet.</p>}
              {p.publications.map((x) => (
                <div key={x.id} className="rounded-lg border p-3 text-sm space-y-1">
                  <div className="flex items-center gap-2"><StatusBadge status={x.status} /><span className="truncate font-medium">{x.title}</span></div>
                  <div className="text-xs text-muted-foreground">{x.publish_at ? `Scheduled ${fmtDate(x.publish_at)}` : `Created ${fmtDate(x.created_at)}`} · {x.privacy}</div>
                  {x.youtube_video_id && <a className="text-xs text-primary hover:underline" href={`https://youtube.com/shorts/${x.youtube_video_id}`} target="_blank" rel="noreferrer">youtube.com/shorts/{x.youtube_video_id}</a>}
                  {(x.error || x.message) && <p className={cn("text-xs", x.error ? "text-red-400" : "text-muted-foreground")}>{x.error ?? x.message}</p>}
                </div>
              ))}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </>
  );
}
