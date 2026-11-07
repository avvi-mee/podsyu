"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import {
  Captions, Check, Download, Film, Loader2, MoreHorizontal, Play, RefreshCw, Save, Send, SlidersHorizontal, Sparkles, Trash2, X,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Slider } from "@/components/ui/slider";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { ProgressBar, StatusBadge } from "@/components/common";
import { CaptionEditor, CaptionPreview, presetStyle } from "@/components/caption-editor";
import { PublishDialog } from "@/components/publish-dialog";
import { api, API, ENGINE_LABEL, fmtTime, MUSIC_LEVELS, type CaptionStyle, type MusicTrack, type Options, type Short } from "@/lib/api";
import { useLive } from "@/lib/live";
import { cn } from "@/lib/utils";

type Props = {
  short: Short; meta: Options | null; projectStyle?: CaptionStyle | null; selected?: boolean;
  onSelect?: (v: boolean) => void; onChanged: () => void; engine?: string | null; canRender?: boolean;
};

export function ShortCard({ short, meta, projectStyle, selected, onSelect, onChanged, engine: engineProp, canRender = short.source_available !== false }: Props) {
  const engine = short.engine ?? engineProp ?? "podcast";
  const det = short.details ?? {};
  const { jobs } = useLive();
  const job = jobs.find((j) => j.short_id === short.id && (j.status === "running" || j.status === "queued"));
  const [form, setForm] = useState({ title: short.title, description: short.description, hashtags: short.hashtags });
  const [publishOpen, setPublishOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const dirty = form.title !== short.title || form.description !== short.description || form.hashtags !== short.hashtags;

  // Pick up server-side changes (e.g. regenerated title) without an effect.
  const [seen, setSeen] = useState(short);
  if (seen.title !== short.title || seen.description !== short.description || seen.hashtags !== short.hashtags) {
    setSeen(short);
    setForm({ title: short.title, description: short.description, hashtags: short.hashtags });
  }

  const call = async (path: string, init: Parameters<typeof api>[1], ok: string) => {
    try {
      await api(path, init);
      toast.success(ok);
      onChanged();
    } catch (e) {
      toast.error((e as Error).message);
    }
  };
  const save = () => call(`/api/shorts/${short.id}`, { method: "PATCH", json: form }, "Saved");
  const regen = (field: string) => call(`/api/shorts/${short.id}/regenerate`, { method: "POST", json: { field } }, `Regenerating ${field}...`);
  const review = (r: string) => call(`/api/shorts/${short.id}`, { method: "PATCH", json: { review: r } }, r === "approved" ? "Approved" : r === "rejected" ? "Rejected" : "Reset");
  const remove = () => confirm("Delete this short and its video file?") && call(`/api/shorts/${short.id}`, { method: "DELETE" }, "Short deleted");

  const busy = !!job || short.busy;
  const yt = short.youtube_id;
  const renderClip = () => {
    if (!canRender && !confirm("Only continue if you own this video or have the rights holder's permission to download and edit it.\n\nDownload the video and render this clip?")) return;
    call(`/api/creators/projects/${short.project_id}/render`, { method: "POST", json: { ids: [short.id], ...(canRender ? {} : { authorized: true }) } },
      canRender ? "Rendering clip..." : "Downloading the video, then rendering...");
  };
  const canEdit = engine === "asmr" || short.source_available !== false; // story shorts render from their narration
  const latestPub = short.publications?.[0];
  const v = short.updated_at; // cache-buster after re-render

  return (
    <Card className={cn("p-0 overflow-hidden gap-0 lift", selected && "ring-2 ring-primary", short.review === "rejected" && "opacity-60")}>
      <div className="flex flex-col sm:flex-row">
        {/* LEFT: video */}
        <div className="sm:w-56 shrink-0 bg-black/40 p-3 flex flex-col gap-2">
          <div className="relative aspect-[9/16] rounded-lg overflow-hidden bg-muted">
            {short.status === "ready" && short.video_path ? (
              <video key={v} src={`${API}/api/shorts/${short.id}/video?v=${encodeURIComponent(v)}`} poster={`${API}/api/shorts/${short.id}/thumbnail?v=${encodeURIComponent(v)}`}
                controls preload="none" playsInline className="size-full object-cover" />
            ) : short.status === "candidate" && yt ? (
              previewing ? (
                <iframe className="absolute inset-0 size-full" title="Preview this moment on YouTube" allow="autoplay; encrypted-media; picture-in-picture" allowFullScreen
                  src={`https://www.youtube-nocookie.com/embed/${yt}?start=${Math.floor(short.start)}&end=${Math.ceil(short.end)}&autoplay=1&playsinline=1&rel=0`} />
              ) : (
                <button type="button" onClick={() => setPreviewing(true)} className="group absolute inset-0" aria-label="Preview this moment">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={`https://i.ytimg.com/vi/${yt}/hqdefault.jpg`} alt="" className="size-full object-cover opacity-50 transition-opacity group-hover:opacity-75" />
                  <span className="absolute inset-0 flex flex-col items-center justify-center gap-1.5 text-xs font-medium">
                    <Play className="size-10 fill-white text-white drop-shadow" /> Preview {fmtTime(short.start)}–{fmtTime(short.end)}
                  </span>
                </button>
              )
            ) : short.status === "candidate" ? (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-center p-3">
                <Film className="size-6 text-primary" />
                <p className="text-xs text-muted-foreground">Clip candidate - not rendered yet</p>
              </div>
            ) : (
              <div className="absolute inset-0 grid place-items-center text-center p-3">
                {short.status === "failed" ? <X className="size-6 text-red-400" /> : <Film className="size-6 text-muted-foreground" />}
              </div>
            )}
            {job && (
              <div className="absolute inset-x-0 bottom-0 bg-black/75 p-2 space-y-1">
                <div className="flex items-center gap-1.5 text-[11px]"><Loader2 className="size-3 animate-spin" />{job.stage || "queued"} {Math.round(job.progress * 100)}%</div>
                <ProgressBar value={job.progress} />
              </div>
            )}
          </div>
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span className="tabular-nums">{fmtTime(short.end - short.start)}</span>
            {short.status === "candidate" ? (
              <Button size="xs" disabled={busy || (!canRender && !yt)} onClick={renderClip}><Sparkles /> Render</Button>
            ) : (
              <Button size="xs" variant="outline" disabled={short.status !== "ready"} render={<a href={`${API}/api/shorts/${short.id}/download`} />} nativeButton={false}>
                <Download /> MP4
              </Button>
            )}
          </div>
          {short.status === "candidate" && !canRender && (
            <p className="text-[11px] leading-snug text-amber-300">
              {yt ? "Render asks you to confirm you own this video or have permission, then downloads it." : "Upload the authorized video file (top of the page) to render."}
            </p>
          )}
        </div>

        {/* RIGHT: metadata */}
        <div className="flex-1 min-w-0 p-4 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            {onSelect && <Checkbox checked={!!selected} onCheckedChange={(c) => onSelect(c === true)} aria-label="Select short" />}
            {engineProp === undefined && <Badge variant="secondary" className="border-0">{ENGINE_LABEL[engine] ?? engine}</Badge>}
            {engine !== "asmr" && engine !== "cutting" && (
              <Badge className="bg-primary/20 text-yellow-200 border-0 tabular-nums" title={engine === "creator" ? "Entertainment score (not a virality prediction)" : "Engagement potential"}>
                <Sparkles className="size-3" /> {short.score}
              </Badge>
            )}
            {(short.status !== "ready" || short.review === "none") && <StatusBadge status={short.status} />}
            {short.review !== "none" && <StatusBadge status={short.review} />}
            {latestPub && <StatusBadge status={latestPub.status} className="normal-case" />}
            <span className="text-xs text-muted-foreground tabular-nums ml-auto">{fmtTime(short.start)} → {fmtTime(short.end)}</span>
          </div>

          <div className="space-y-1">
            <div className="flex items-center justify-between">
              <Label className="text-xs text-muted-foreground">Title</Label>
              <Button size="icon-xs" variant="ghost" disabled={busy} onClick={() => regen("title")} aria-label="Regenerate title" title="Regenerate title with AI"><RefreshCw /></Button>
            </div>
            <Input value={form.title} maxLength={100} onChange={(e) => setForm({ ...form, title: e.target.value })} className="font-medium" />
          </div>
          <div className="space-y-1">
            <div className="flex items-center justify-between">
              <Label className="text-xs text-muted-foreground">Description</Label>
              <Button size="icon-xs" variant="ghost" disabled={busy} onClick={() => regen("description")} aria-label="Regenerate description" title="Regenerate description with AI"><RefreshCw /></Button>
            </div>
            <Textarea rows={2} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </div>
          <div className="space-y-1">
            <div className="flex items-center justify-between">
              <Label className="text-xs text-muted-foreground">Hashtags</Label>
              <Button size="icon-xs" variant="ghost" disabled={busy} onClick={() => regen("hashtags")} aria-label="Regenerate hashtags" title="Regenerate hashtags with AI"><RefreshCw /></Button>
            </div>
            <Input value={form.hashtags} onChange={(e) => setForm({ ...form, hashtags: e.target.value })} className="text-yellow-300" />
          </div>

          <details className="text-sm group">
            <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground">Details</summary>
            <div className="mt-2 space-y-2 text-sm">
              {(det.scene || short.category) && (
                <p><span className="text-muted-foreground">{det.scene ? "Scene: " : "Category: "}</span>{det.scene ?? ""}{det.scene && short.category ? " · " : ""}<span className="capitalize">{short.category}</span></p>
              )}
              {short.hook && <p><span className="text-muted-foreground">Hook: </span>{short.hook}</p>}
              {short.reason && <p><span className="text-muted-foreground">Why: </span>{short.reason}</p>}
              <p className="text-muted-foreground leading-relaxed max-h-40 overflow-y-auto">{short.transcript}</p>
              {short.framing && <p className="text-xs text-muted-foreground">Framing: {short.framing}</p>}
              {det.scores && (
                <p className="text-xs text-muted-foreground">
                  Scores: {Object.entries(det.scores).map(([k, v]) => `${k} ${v ?? "-"}/10`).join(" · ")}
                  {det.signals?.audio_peak != null && ` · audio reaction ${Math.round((det.signals.audio_peak as number) * 100)}%`}
                  {det.signals?.motion != null && ` · motion ${Math.round((det.signals.motion as number) * 100)}%`}
                  {det.analysis && ` · ${det.analysis} analysis`}
                </p>
              )}
            </div>
          </details>
          {short.error && <p className="text-xs text-red-400">{short.error}</p>}
          {latestPub?.error && <p className="text-xs text-red-400">Upload: {latestPub.error}</p>}
          {latestPub?.message && !latestPub.error && <p className="text-xs text-muted-foreground">YouTube: {latestPub.message}</p>}

          <div className="flex flex-wrap gap-2 pt-1">
            {dirty && <Button size="sm" onClick={save}><Save /> Save</Button>}
            <Button size="sm" variant={short.review === "approved" ? "secondary" : "outline"} onClick={() => review(short.review === "approved" ? "none" : "approved")}>
              <Check className="text-emerald-400" /> {short.review === "approved" ? "Approved" : "Approve"}
            </Button>
            <Button size="sm" variant="outline" onClick={() => review(short.review === "rejected" ? "none" : "rejected")}>
              <X className="text-red-400" /> {short.review === "rejected" ? "Rejected" : "Reject"}
            </Button>
            <Button size="sm" variant="outline" disabled={short.status !== "ready"} onClick={() => setPublishOpen(true)}>
              <Send /> Publish
            </Button>
            <Button size="sm" variant="outline" disabled={busy || !meta || !canEdit || short.status === "candidate"} onClick={() => setEditOpen(true)}>
              <SlidersHorizontal /> Captions &amp; framing
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger render={<Button size="icon-sm" variant="ghost" aria-label="More actions" />}>
                <MoreHorizontal />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {engine === "asmr" ? (
                  <DropdownMenuItem disabled={busy} onClick={() => call(`/api/asmr/projects/${short.project_id}/regenerate`, { method: "POST", json: { redo: "voice" } }, "Regenerating voice & captions...")}>
                    <Captions /> Regenerate voice &amp; captions
                  </DropdownMenuItem>
                ) : (
                  <DropdownMenuItem disabled={busy || short.source_available === false || short.status === "candidate"} onClick={() => call(`/api/shorts/${short.id}/recaption`, { method: "POST" }, "Re-transcribing clip for new captions...")}>
                    <Captions /> Regenerate captions
                  </DropdownMenuItem>
                )}
                <DropdownMenuItem disabled={busy || !canEdit || short.status === "candidate"} onClick={() => call(`/api/shorts/${short.id}/render`, { method: "POST" }, "Re-render queued")}>
                  <RefreshCw /> Re-render video
                </DropdownMenuItem>
                <DropdownMenuItem disabled={busy} onClick={() => regen("all")}>
                  <Sparkles /> Regenerate all metadata
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem variant="destructive" onClick={remove}>
                  <Trash2 /> Delete short
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </div>
      {publishOpen && <PublishDialog short={{ ...short, ...form }} open onOpenChange={setPublishOpen} onDone={onChanged} />}
      {meta && editOpen && (
        <EditDialog short={short} meta={meta} projectStyle={projectStyle} open={editOpen} onOpenChange={setEditOpen} onDone={onChanged} engine={engine} />
      )}
    </Card>
  );
}

function EditDialog({ short, meta, projectStyle, open, onOpenChange, onDone, engine }: {
  short: Short; meta: Options; projectStyle?: CaptionStyle | null; open: boolean; onOpenChange: (o: boolean) => void; onDone: () => void;
  engine: string;
}) {
  const story = engine === "asmr"; // no source video: no framing or trim
  const [style, setStyle] = useState<CaptionStyle>(short.caption_style ?? projectStyle ?? presetStyle(meta, "hormozi"));
  const [crop, setCrop] = useState({ mode: short.crop_mode, x: short.crop_x });
  const [range, setRange] = useState({ start: short.start, end: short.end });
  // music "project" = follow the project's choice, "none" = no music, otherwise a track id
  const [bgm, setBgm] = useState({ track: short.music ?? "project", volume: short.music_volume ?? 0.1 });
  const [tracks, setTracks] = useState<MusicTrack[]>([]);
  useEffect(() => {
    api<MusicTrack[]>("/api/music").then(setTracks).catch(() => {});
  }, []);
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    try {
      await api(`/api/shorts/${short.id}`, {
        method: "PATCH",
        json: {
          caption_style: style, ...(story ? {} : { crop_mode: crop.mode, crop_x: crop.x, start: range.start, end: range.end }),
          music: bgm.track === "project" ? null : bgm.track, music_volume: bgm.track === "project" ? null : bgm.volume,
        },
      });
      toast.success("Saved - re-rendering this short");
      onOpenChange(false);
      onDone();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  // Preview uses the saved short (timing/crop) with the unsaved caption style.
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-4xl max-h-[92vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Captions, framing &amp; trim</DialogTitle>
          <DialogDescription>Changes apply to this short only and trigger a re-render.</DialogDescription>
        </DialogHeader>
        <div className="grid md:grid-cols-[1fr_260px] gap-6">
          <div className="space-y-6">
            <CaptionEditor style={style} onChange={setStyle} meta={meta} />
            {!story && <div className="space-y-3 rounded-lg border p-3">
              <div className="text-sm font-medium">Vertical framing</div>
              <div className="flex gap-2">
                {(["auto", "manual"] as const).map((m) => (
                  <Button key={m} size="sm" variant={crop.mode === m ? "default" : "outline"} onClick={() => setCrop({ ...crop, mode: m })}>
                    {m === "auto" ? "Auto (follow speaker)" : "Manual position"}
                  </Button>
                ))}
              </div>
              {crop.mode === "manual" && (
                <div className="space-y-2">
                  <Label className="text-xs text-muted-foreground">Horizontal position · {Math.round(crop.x * 100)}% (0 = left edge, 100 = right edge)</Label>
                  <Slider min={0} max={1} step={0.01} value={[crop.x]} onValueChange={(v) => setCrop({ ...crop, x: Array.isArray(v) ? v[0] : (v as number) })} />
                </div>
              )}
            </div>}
            <div className="space-y-2 rounded-lg border p-3">
              <div className="text-sm font-medium">Background music</div>
              <div className="flex flex-wrap gap-2">
                <NativeSelect className="flex-1" value={bgm.track} onChange={(e) => setBgm({ ...bgm, track: e.target.value })} aria-label="Background music">
                  <NativeSelectOption value="project">Same as project</NativeSelectOption>
                  <NativeSelectOption value="none">No music</NativeSelectOption>
                  {tracks.map((t) => <NativeSelectOption key={t.id} value={String(t.id)}>{t.title}</NativeSelectOption>)}
                </NativeSelect>
                <NativeSelect value={bgm.volume} disabled={bgm.track === "project" || bgm.track === "none"} onChange={(e) => setBgm({ ...bgm, volume: +e.target.value })} aria-label="Music volume">
                  {MUSIC_LEVELS.map((l) => <NativeSelectOption key={l.v} value={l.v}>{l.label}</NativeSelectOption>)}
                </NativeSelect>
              </div>
              <p className="text-xs text-muted-foreground">Plays low and dips automatically while people talk.</p>
            </div>
            {!story && <div className="space-y-2 rounded-lg border p-3">
              <div className="text-sm font-medium">Trim (seconds in source video)</div>
              <div className="grid grid-cols-2 gap-3">
                <Input type="number" step={0.1} value={range.start} onChange={(e) => setRange({ ...range, start: +e.target.value })} aria-label="Start" />
                <Input type="number" step={0.1} value={range.end} onChange={(e) => setRange({ ...range, end: +e.target.value })} aria-label="End" />
              </div>
              <p className="text-xs text-muted-foreground">{fmtTime(range.start)} → {fmtTime(range.end)} · {(range.end - range.start).toFixed(1)}s</p>
            </div>}
          </div>
          <div className="space-y-3">
            <CaptionPreview style={style} shortId={short.id} />
            <p className="text-xs text-muted-foreground">Real frame rendered by FFmpeg with these captions (framing preview uses the saved setting).</p>
            <Button className="w-full" disabled={busy} onClick={save}>
              {busy ? <Loader2 className="animate-spin" /> : <Save />} Save &amp; re-render
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
