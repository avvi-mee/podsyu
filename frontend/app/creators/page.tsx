"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { CheckCircle2, FileVideo, Gamepad2, Info, Loader2, Search, Sparkles, Upload, XCircle } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Empty, JobRow, PageHeader, ProgressBar, StatusBadge } from "@/components/common";
import { api, API, fmtDate, fmtTime, type Project } from "@/lib/api";
import { useLive, useLiveRefresh } from "@/lib/live";

type Info = { title: string; channel: string | null; duration: number | null; thumbnail: string | null; url: string; captions: boolean; manual_captions: boolean };
type CreatorProject = Project & { candidates: number; rendered: number };
const CATEGORIES = ["challenge", "gaming", "stream", "reaction", "comedy", "vlog", "sports", "prank", "other"];

export default function CreatorsPage() {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [info, setInfo] = useState<Info | null>(null);
  const [fetching, setFetching] = useState(false);
  const [form, setForm] = useState({ creator: "", video_category: "challenge", clip_seconds: 15, layout: "auto", authorized: false });
  const [file, setFile] = useState<File | null>(null);
  const [uploadPct, setUploadPct] = useState<number | null>(null);
  const [projects, setProjects] = useState<CreatorProject[] | null>(null);
  const [busy, setBusy] = useState(false);
  const { jobs } = useLive();
  const queue = jobs.filter((j) => j.type === "creator_analyze" && (j.status === "running" || j.status === "queued"));

  const load = useCallback(() => api<CreatorProject[]>("/api/creators/projects").then(setProjects).catch((e) => toast.error(e.message)), []);
  useEffect(() => {
    load();
  }, [load]);
  useLiveRefresh(load, (j) => j.type === "creator_analyze" || j.type === "render");

  const inspect = async () => {
    setFetching(true);
    setInfo(null);
    try {
      const i = await api<Info>("/api/creators/inspect", { method: "POST", json: { url } });
      setInfo(i);
      setForm((f) => ({ ...f, creator: f.creator || i.channel || "" }));
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setFetching(false);
    }
  };

  const analyzeUrl = async () => {
    setBusy(true);
    try {
      const r = await api<{ project_id: number }>("/api/creators/projects", { method: "POST", json: { url: info?.url ?? url, info, ...form } });
      toast.success(form.authorized ? "Downloading authorized media and analysing..." : "Analysing published captions (transcript-only)...");
      router.push(`/projects/${r.project_id}`);
    } catch (e) {
      toast.error((e as Error).message);
      setBusy(false);
    }
  };

  const analyzeFile = () => {
    if (!file) return;
    setUploadPct(0);
    const req = new XMLHttpRequest();
    req.open("POST", `${API}/api/projects/upload?filename=${encodeURIComponent(file.name)}&engine=creator`);
    req.upload.onprogress = (e) => e.lengthComputable && setUploadPct(e.loaded / e.total);
    req.onload = async () => {
      setUploadPct(null);
      const body = JSON.parse(req.responseText || "{}");
      if (req.status >= 300) return toast.error(body.detail ?? "Upload failed");
      try {
        await api(`/api/creators/projects/${body.id}/analyze`, { method: "POST", json: { ...form, authorized: true } });
        router.push(`/projects/${body.id}`);
      } catch (e) {
        toast.error((e as Error).message);
      }
    };
    req.onerror = () => { setUploadPct(null); toast.error("Upload failed - is the backend running?"); };
    req.setRequestHeader("Content-Type", "application/octet-stream");
    req.send(file);
  };

  return (
    <>
      <PageHeader title="Famous Creators Clipper" description="Find the funniest moments. Turn them into Shorts." />
      <div className="mb-4 flex gap-2 rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-sm">
        <Info className="size-4 mt-0.5 shrink-0 text-amber-300" />
        <span>Only clip videos you own or have permission to use. A link alone gives metadata and published captions for analysis; rendering needs the video file, either downloaded with your authorization or uploaded by you.</span>
      </div>
      <div className="grid lg:grid-cols-5 gap-4">
        <Card className="lg:col-span-3">
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><Gamepad2 className="size-4 text-primary" /> Video</CardTitle>
            <CardDescription>Paste a YouTube link and/or upload the authorized video file.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); inspect(); }}>
              <Input placeholder="https://www.youtube.com/watch?v=..." value={url} onChange={(e) => setUrl(e.target.value)} aria-label="YouTube URL" />
              <Button type="submit" disabled={!url || fetching}>{fetching ? <Loader2 className="animate-spin" /> : <Search />} Inspect</Button>
            </form>
            {info && (
              <div className="flex gap-4 rounded-xl border bg-muted/30 p-3">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                {info.thumbnail && <img src={info.thumbnail} alt="" className="w-44 aspect-video object-cover rounded-lg" />}
                <div className="min-w-0 space-y-1 text-sm">
                  <div className="font-medium leading-snug">{info.title}</div>
                  <div className="text-muted-foreground">{info.channel} · {fmtTime(info.duration)}</div>
                  <div className="flex items-center gap-1.5">
                    {info.captions ? <CheckCircle2 className="size-4 text-emerald-400" /> : <XCircle className="size-4 text-red-400" />}
                    Transcript: {info.captions ? (info.manual_captions ? "creator captions available" : "auto-captions available") : "none - media needed"}
                  </div>
                  <div className="flex items-center gap-1.5">
                    {form.authorized ? <CheckCircle2 className="size-4 text-emerald-400" /> : <Info className="size-4 text-amber-300" />}
                    Media: {form.authorized ? "will download (you confirmed authorization)" : "not authorized - transcript-only analysis, upload the file to render"}
                  </div>
                </div>
              </div>
            )}
            <label className="flex items-start gap-3 rounded-lg border p-3 text-sm cursor-pointer">
              <Checkbox checked={form.authorized} onCheckedChange={(v) => setForm({ ...form, authorized: v === true })} className="mt-0.5" />
              <span>I own this video or have the rights holder&apos;s permission to download, edit and republish it.</span>
            </label>
            <Button className="w-full" disabled={!info || busy || (!info.captions && !form.authorized)} onClick={analyzeUrl}>
              {busy ? <Loader2 className="animate-spin" /> : <Sparkles />} Analyze video {form.authorized ? "(download + full analysis)" : "(captions only)"}
            </Button>
            <div className="border-t pt-4 space-y-2">
              <Label className="text-xs text-muted-foreground">Or upload the authorized video file (full audio + visual analysis)</Label>
              <div className="flex gap-2">
                <label className="flex-1">
                  <input type="file" accept=".mp4,.mov,.mkv,.webm,video/*" className="sr-only" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
                  <span className="flex h-8 items-center gap-2 rounded-lg border px-3 text-sm cursor-pointer hover:bg-muted truncate"><FileVideo className="size-4" /> {file?.name ?? "Choose video file..."}</span>
                </label>
                <Button variant="outline" disabled={!file || uploadPct !== null} onClick={analyzeFile}><Upload /> Upload &amp; analyze</Button>
              </div>
              {uploadPct !== null && <ProgressBar value={uploadPct} />}
            </div>
          </CardContent>
        </Card>
        <Card className="lg:col-span-2">
          <CardHeader><CardTitle>Clip settings</CardTitle><CardDescription>Applies to this analysis.</CardDescription></CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-1.5"><Label className="text-xs text-muted-foreground">Creator name</Label>
              <Input value={form.creator} onChange={(e) => setForm({ ...form, creator: e.target.value })} placeholder="e.g. the channel name" /></div>
            <div className="space-y-1.5"><Label className="text-xs text-muted-foreground">Video category</Label>
              <NativeSelect className="w-full" value={form.video_category} onChange={(e) => setForm({ ...form, video_category: e.target.value })}>
                {CATEGORIES.map((c) => <NativeSelectOption key={c} value={c}>{c}</NativeSelectOption>)}
              </NativeSelect></div>
            <div className="space-y-1.5"><Label className="text-xs text-muted-foreground">Clip length</Label>
              <NativeSelect className="w-full" value={form.clip_seconds} onChange={(e) => setForm({ ...form, clip_seconds: +e.target.value })}>
                <NativeSelectOption value={10}>~10 seconds (8-13 s)</NativeSelectOption>
                <NativeSelectOption value={15}>~15 seconds (12-18 s) - default</NativeSelectOption>
                <NativeSelectOption value={20}>~20 seconds (16-24 s)</NativeSelectOption>
                <NativeSelectOption value={30}>~30 seconds (24-34 s)</NativeSelectOption>
              </NativeSelect></div>
            <div className="space-y-1.5"><Label className="text-xs text-muted-foreground">Vertical layout</Label>
              <NativeSelect className="w-full" value={form.layout} onChange={(e) => setForm({ ...form, layout: e.target.value })}>
                <NativeSelectOption value="auto">Follow the speaker / webcam (crop)</NativeSelectOption>
                <NativeSelectOption value="full">Full frame - keep gameplay &amp; on-screen info</NativeSelectOption>
              </NativeSelect></div>
          </CardContent>
        </Card>
      </div>

      <div className="grid lg:grid-cols-3 gap-4 mt-4">
        <Card className="lg:col-span-2">
          <CardHeader><CardTitle>Creator projects</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            {projects?.length === 0 && <Empty icon={Gamepad2} title="No creator videos analysed yet" />}
            {projects?.map((p) => (
              <Link key={p.id} href={`/projects/${p.id}`} className="flex items-center gap-3 rounded-lg p-2 -mx-2 hover:bg-muted/50">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={`${API}/api/projects/${p.id}/thumbnail`} alt="" className="w-24 aspect-video rounded-md object-cover bg-muted" onError={(e) => (e.currentTarget.style.visibility = "hidden")} />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{p.title}</div>
                  <div className="text-xs text-muted-foreground">{(p.options?.creator as string) || p.channel || "-"} · {p.candidates} candidates · {p.rendered} rendered · {fmtDate(p.created_at, undefined, false)}</div>
                </div>
                <StatusBadge status={p.status} />
              </Link>
            ))}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Processing queue</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            {queue.length === 0 && <p className="text-sm text-muted-foreground">Nothing analysing right now.</p>}
            {queue.map((j) => <JobRow key={j.id} job={j} />)}
          </CardContent>
        </Card>
      </div>
    </>
  );
}
