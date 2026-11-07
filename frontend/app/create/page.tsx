"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import Link from "next/link";
import { FileVideo, Loader2, Rocket, Sparkles, Upload, MonitorPlay } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PageHeader, ProgressBar } from "@/components/common";
import { api, API, fmtTime, MUSIC_LEVELS, type MusicTrack, type Options, type ProjectDetail } from "@/lib/api";

type Info = { title: string; channel: string | null; duration: number | null; thumbnail: string | null; url: string };

export default function CreatePage() {
  const router = useRouter();
  const [tab, setTab] = useState<"youtube" | "local">("youtube");
  const [meta, setMeta] = useState<Options | null>(null);
  const [tracks, setTracks] = useState<MusicTrack[]>([]);
  const [opts, setOpts] = useState({ min_duration: 30, max_duration: 90, num_shorts: 5, category: "any", strategy: "balanced", preset: "hormozi", auto_delete: false, music: "none", music_volume: 0.1 });
  // YouTube
  const [url, setUrl] = useState("");
  const [info, setInfo] = useState<Info | null>(null);
  const [authorized, setAuthorized] = useState(false);
  const [fetching, setFetching] = useState(false);
  // Upload
  const [file, setFile] = useState<File | null>(null);
  const [uploadPct, setUploadPct] = useState<number | null>(null);
  const [uploaded, setUploaded] = useState<ProjectDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const xhr = useRef<XMLHttpRequest | null>(null);

  useEffect(() => {
    api<Options>("/api/meta/options").then(setMeta).catch((e) => toast.error(e.message));
    api<MusicTrack[]>("/api/music").then(setTracks).catch(() => {});
    api<{ settings: Record<string, number & string> }>("/api/settings")
      .then(({ settings: s }) => { setOpts((o) => ({ ...o, min_duration: s.min_duration, max_duration: s.max_duration, num_shorts: s.num_shorts, preset: s.default_caption_preset, auto_delete: Boolean(s.auto_cleanup_source) })); })
      .catch(() => {});
    return () => xhr.current?.abort();
  }, []);

  const fetchInfo = async () => {
    setFetching(true);
    setInfo(null);
    try {
      setInfo(await api<Info>("/api/import/youtube/preview", { method: "POST", json: { url } }));
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setFetching(false);
    }
  };

  const upload = (f: File) => {
    setFile(f);
    setUploaded(null);
    setUploadPct(0);
    const req = new XMLHttpRequest();
    xhr.current = req;
    req.open("POST", `${API}/api/projects/upload?filename=${encodeURIComponent(f.name)}`);
    req.upload.onprogress = (e) => e.lengthComputable && setUploadPct(e.loaded / e.total);
    req.onload = () => {
      setUploadPct(null);
      const body = JSON.parse(req.responseText || "{}");
      if (req.status >= 200 && req.status < 300) {
        setUploaded(body);
        toast.success("Video uploaded and validated");
      } else toast.error(body.detail ?? "Upload failed");
    };
    req.onerror = () => {
      setUploadPct(null);
      toast.error("Upload failed - is the backend running?");
    };
    req.setRequestHeader("Content-Type", "application/octet-stream");
    req.send(f);
  };

  const options = {
    min_duration: opts.min_duration, max_duration: opts.max_duration, num_shorts: opts.num_shorts,
    category: opts.category, strategy: opts.strategy, caption_style: { preset: opts.preset }, auto_delete_source: opts.auto_delete,
    music: opts.music, music_volume: opts.music_volume,
  };

  const start = async () => {
    setBusy(true);
    try {
      let id: number;
      if (tab === "youtube") {
        const p = await api<ProjectDetail>("/api/projects/youtube", { method: "POST", json: { url: info?.url ?? url, authorized, info, options } });
        id = p.id;
      } else {
        id = uploaded!.id;
        await api(`/api/projects/${id}/process`, { method: "POST", json: { options } });
      }
      toast.success("Processing started");
      router.push(`/projects/${id}`);
    } catch (e) {
      toast.error((e as Error).message);
      setBusy(false);
    }
  };

  const ready = tab === "youtube" ? !!info && authorized : !!uploaded;
  const durErr = opts.min_duration >= opts.max_duration ? "Minimum must be lower than maximum" : "";

  return (
    <>
      <PageHeader title="Podcast Clipper" description="Import a podcast episode and let the local AI find, cut, frame and caption the best moments.">
        <Button variant="outline" render={<Link href="/autopilot" />} nativeButton={false}><Rocket /> Fully automatic? Use Autopilot</Button>
      </PageHeader>
      <div className="grid lg:grid-cols-5 gap-4">
        <div className="lg:col-span-3 space-y-4">
        <Card>
          <CardHeader>
            <CardTitle>1 · Source video</CardTitle>
            <CardDescription>Only import videos you own or are authorized to download and edit.</CardDescription>
          </CardHeader>
          <CardContent>
            <Tabs value={tab} onValueChange={(v) => setTab(v as "youtube" | "local")}>
              <TabsList className="mb-4">
                <TabsTrigger value="youtube"><MonitorPlay className="size-4" /> YouTube URL</TabsTrigger>
                <TabsTrigger value="local"><FileVideo className="size-4" /> Upload local file</TabsTrigger>
              </TabsList>

              <TabsContent value="youtube" className="space-y-4">
                <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); fetchInfo(); }}>
                  <Input placeholder="https://www.youtube.com/watch?v=..." value={url} onChange={(e) => setUrl(e.target.value)} aria-label="YouTube URL" />
                  <Button type="submit" disabled={!url || fetching}>
                    {fetching ? <Loader2 className="animate-spin" /> : <MonitorPlay />} Import video
                  </Button>
                </form>
                {info && (
                  <div className="flex gap-4 rounded-xl border bg-muted/30 p-3">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    {info.thumbnail && <img src={info.thumbnail} alt="" className="w-44 aspect-video object-cover rounded-lg" />}
                    <div className="min-w-0 space-y-1">
                      <div className="font-medium leading-snug">{info.title}</div>
                      <div className="text-sm text-muted-foreground">{info.channel}</div>
                      <div className="text-sm text-muted-foreground">Duration {fmtTime(info.duration)}</div>
                    </div>
                  </div>
                )}
                {info && (
                  <label className="flex items-start gap-3 rounded-lg border p-3 text-sm cursor-pointer">
                    <Checkbox checked={authorized} onCheckedChange={(v) => setAuthorized(v === true)} className="mt-0.5" />
                    <span>I own this video or have permission from the rights holder to download, edit and republish it.</span>
                  </label>
                )}
                <p className="text-xs text-muted-foreground">
                  Private, members-only, age-restricted or DRM-protected videos can&apos;t be downloaded. Download your own video from YouTube Studio and use &quot;Upload local file&quot; instead.
                </p>
              </TabsContent>

              <TabsContent value="local" className="space-y-4">
                <label
                  className="flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed p-10 text-center cursor-pointer hover:border-primary/50 hover:bg-primary/5 transition-colors"
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={(e) => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) upload(f); }}
                >
                  <Upload className="size-8 text-primary" />
                  <span className="font-medium">Drop a video here or click to browse</span>
                  <span className="text-xs text-muted-foreground">MP4, MOV, MKV or WEBM</span>
                  <input type="file" accept=".mp4,.mov,.mkv,.webm,video/*" className="sr-only" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
                </label>
                {uploadPct !== null && (
                  <div className="space-y-1.5">
                    <div className="flex justify-between text-sm"><span className="truncate">{file?.name}</span><span className="tabular-nums">{Math.round(uploadPct * 100)}%</span></div>
                    <ProgressBar value={uploadPct} />
                    {uploadPct >= 1 && <p className="text-xs text-muted-foreground">Validating video...</p>}
                  </div>
                )}
                {uploaded && (
                  <div className="rounded-xl border bg-muted/30 p-3 text-sm space-y-1">
                    <div className="font-medium">{uploaded.title}</div>
                    <div className="text-muted-foreground">{fmtTime(uploaded.duration)} · {uploaded.width}×{uploaded.height}</div>
                  </div>
                )}
              </TabsContent>
            </Tabs>
          </CardContent>
        </Card>

        </div>

        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>2 · Clip settings</CardTitle>
            <CardDescription>How the AI should pick moments.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-3 gap-3">
              <Field label="Min (s)"><Input type="number" min={10} max={180} value={opts.min_duration} onChange={(e) => setOpts({ ...opts, min_duration: +e.target.value })} /></Field>
              <Field label="Max (s)"><Input type="number" min={15} max={180} value={opts.max_duration} onChange={(e) => setOpts({ ...opts, max_duration: +e.target.value })} /></Field>
              <Field label="Shorts"><Input type="number" min={1} max={30} value={opts.num_shorts} onChange={(e) => setOpts({ ...opts, num_shorts: +e.target.value })} /></Field>
            </div>
            {durErr && <p className="text-xs text-red-400">{durErr}</p>}
            <Field label="Content category">
              <NativeSelect className="w-full" value={opts.category} onChange={(e) => setOpts({ ...opts, category: e.target.value })}>
                <NativeSelectOption value="any">Any - best overall</NativeSelectOption>
                {meta?.categories.map((c) => <NativeSelectOption key={c} value={c}>{c[0].toUpperCase() + c.slice(1)}</NativeSelectOption>)}
              </NativeSelect>
            </Field>
            <Field label="Selection strategy">
              <NativeSelect className="w-full" value={opts.strategy} onChange={(e) => setOpts({ ...opts, strategy: e.target.value })}>
                {meta && Object.keys(meta.strategies).map((s) => <NativeSelectOption key={s} value={s}>{s[0].toUpperCase() + s.slice(1)}</NativeSelectOption>)}
              </NativeSelect>
              <p className="text-xs text-muted-foreground mt-1">{meta?.strategies[opts.strategy]}</p>
            </Field>
            <Field label="Caption preset">
              <NativeSelect className="w-full" value={opts.preset} onChange={(e) => setOpts({ ...opts, preset: e.target.value })}>
                {meta && Object.entries(meta.presets).map(([k, p]) => <NativeSelectOption key={k} value={k}>{p.name}</NativeSelectOption>)}
              </NativeSelect>
            </Field>
            <Field label="Background music">
              <div className="flex gap-2">
                <NativeSelect className="flex-1" value={opts.music} onChange={(e) => setOpts({ ...opts, music: e.target.value })} aria-label="Background music">
                  <NativeSelectOption value="none">No music</NativeSelectOption>
                  {tracks.map((t) => <NativeSelectOption key={t.id} value={String(t.id)}>{t.title}</NativeSelectOption>)}
                </NativeSelect>
                <NativeSelect value={opts.music_volume} disabled={opts.music === "none"} onChange={(e) => setOpts({ ...opts, music_volume: +e.target.value })} aria-label="Music volume">
                  {MUSIC_LEVELS.map((l) => <NativeSelectOption key={l.v} value={l.v}>{l.label}</NativeSelectOption>)}
                </NativeSelect>
              </div>
            </Field>
            <label className="flex items-start gap-3 rounded-lg border p-3 text-sm cursor-pointer">
              <Checkbox checked={opts.auto_delete} onCheckedChange={(v) => setOpts({ ...opts, auto_delete: v === true })} className="mt-0.5" />
              <span>
                Delete the source video when finished
                <span className="block text-xs text-muted-foreground">Saves disk space once all shorts render successfully. You can change this on the project page while it runs.</span>
              </span>
            </label>
            <Button size="lg" className="w-full h-11" disabled={!ready || busy || !!durErr} onClick={start}>
              {busy ? <Loader2 className="animate-spin" /> : <Sparkles />} Generate Shorts
            </Button>
            {!ready && <p className="text-xs text-muted-foreground text-center">{tab === "youtube" ? "Import a video and confirm you're authorized." : "Upload a video first."}</p>}
          </CardContent>
        </Card>
      </div>
    </>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      {children}
    </div>
  );
}
