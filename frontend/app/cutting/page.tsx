"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { CheckCircle2, Loader2, ShieldAlert, Slice, Sparkles, XCircle } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Empty, JobRow, PageHeader } from "@/components/common";
import { ShortCard } from "@/components/short-card";
import { api, API, type ProjectDetail, type Short } from "@/lib/api";
import { useLive, useLiveRefresh } from "@/lib/live";
import { cn } from "@/lib/utils";

type Status = {
  ok: boolean; error?: string; studio_dir: string; presets?: string[];
  versions?: Record<string, string | null>; config?: { object: string; cuts: number; watermark: string };
};
type CutProject = ProjectDetail & { short: Short | null };
const PREVIEWS = [["opening", "Opening"], ["middle_cut", "Middle cut"], ["fall", "Fall"]] as const;
// Studio timing: first hit on frame 29, one every 6 frames, video ends 97 frames after the last hit (24 fps).
const seconds = (n: number) => (29 + 6 * (n - 1) + 97) / 24;

export default function CuttingPage() {
  const [status, setStatus] = useState<Status | null>(null);
  const [form, setForm] = useState({ object: "Papaya", cuts: 50, watermark: "" });
  const [projects, setProjects] = useState<CutProject[]>([]);
  const [busy, setBusy] = useState(false);
  const { jobs } = useLive();
  const queue = jobs.filter((j) => j.type === "cutting" && (j.status === "running" || j.status === "queued"));

  const load = useCallback(() => api<CutProject[]>("/api/cutting/projects").then(setProjects).catch(() => {}), []);
  useEffect(() => {
    api<Status>("/api/cutting/status")
      .then((s) => {
        setStatus(s);
        if (s.config) setForm({ object: s.config.object, cuts: s.config.cuts, watermark: s.config.watermark });
      })
      .catch((e) => toast.error(e.message));
    load();
  }, [load]);
  useLiveRefresh(load, (j) => j.type === "cutting" || j.type === "metadata");

  const valid = form.object.trim() !== "" && Number.isInteger(form.cuts) && form.cuts >= 1 && form.cuts <= 200;
  const generate = async () => {
    setBusy(true);
    try {
      await api("/api/cutting/generate", { method: "POST", json: form });
      toast.success(`Rendering ${form.object} × ${form.cuts} cuts in Blender...`);
      load();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader title="ASMR CUTTING STUDIO" description="Ek object. Kitne cuts? Blender renders a vertical knife-cutting short with a chop on every cut." />
      {status && !status.ok && (
        <div className="mb-4 flex gap-2 rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm">
          <ShieldAlert className="size-4 mt-0.5 shrink-0 text-red-300" />
          <span>{status.error ?? "Blender, ffmpeg or ffprobe was not found."} Studio folder: <code>{status.studio_dir}</code>. Run <code>python studio.py check</code> there.</span>
        </div>
      )}
      <div className="grid lg:grid-cols-5 gap-4">
        <Card className="lg:col-span-3">
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><Slice className="size-4 text-primary" /> New cutting video</CardTitle>
            <CardDescription>Shape, skin, cut surface and sound follow the object. Every video gets new, slightly wonky cut angles.</CardDescription>
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (valid) generate(); }}>
              <div className="grid sm:grid-cols-[1fr_140px] gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="cut-object" className="text-xs text-muted-foreground">Object</Label>
                  <Input id="cut-object" value={form.object} maxLength={60} placeholder="Pick below or type any object"
                    onChange={(e) => setForm({ ...form, object: e.target.value })} />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="cut-count" className="text-xs text-muted-foreground">Cuts</Label>
                  <Input id="cut-count" type="number" min={1} max={200} step={1} value={Number.isNaN(form.cuts) ? "" : form.cuts}
                    onChange={(e) => setForm({ ...form, cuts: e.target.valueAsNumber })} />
                </div>
              </div>
              {!!status?.presets?.length && (
                <div className="space-y-1.5">
                  <p className="text-xs text-muted-foreground">{status.presets.length} ready-made objects (any other name works too, with a generic look)</p>
                  <div className="flex flex-wrap gap-1.5">
                    {status.presets.map((p) => {
                      const name = p[0].toUpperCase() + p.slice(1);
                      const on = form.object.trim().toLowerCase() === p;
                      return (
                        <button key={p} type="button" aria-pressed={on} onClick={() => setForm({ ...form, object: name })}
                          className={cn("rounded-full border px-2.5 py-1 text-xs transition-colors hover:bg-muted", on && "border-primary bg-primary/15 text-primary")}>
                          {name}
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
              <div className="space-y-1.5">
                <Label htmlFor="cut-watermark" className="text-xs text-muted-foreground">Watermark (bottom safe margin)</Label>
                <Input id="cut-watermark" value={form.watermark} maxLength={40} placeholder="@yourhandle" onChange={(e) => setForm({ ...form, watermark: e.target.value })} />
              </div>
              <p className="text-xs text-muted-foreground">
                {valid ? `${form.cuts} knife strokes · counter 0/${form.cuts} → ${form.cuts}/${form.cuts} · ${seconds(form.cuts).toFixed(1)} s video at 540×960, 24 fps` : "Cuts must be a whole number from 1 to 200."}
              </p>
              <Button type="submit" className="w-full" disabled={!valid || busy || status?.ok === false}>
                {busy ? <Loader2 className="animate-spin" /> : <Sparkles />} Generate cutting short
              </Button>
            </form>
          </CardContent>
        </Card>
        <Card className="lg:col-span-2">
          <CardHeader><CardTitle>Studio</CardTitle><CardDescription className="break-all">{status?.studio_dir ?? "Checking tools..."}</CardDescription></CardHeader>
          <CardContent className="space-y-2 text-sm">
            {!status && <Loader2 className="size-4 animate-spin text-muted-foreground" />}
            {status?.versions && Object.entries(status.versions).map(([k, v]) => (
              <div key={k} className="flex items-start gap-2">
                {v ? <CheckCircle2 className="size-4 mt-0.5 shrink-0 text-emerald-400" /> : <XCircle className="size-4 mt-0.5 shrink-0 text-red-400" />}
                <span className="min-w-0"><span className="font-medium">{k === "ffmpeg" ? "FFmpeg" : k === "ffprobe" ? "FFprobe" : "Blender"}</span>{" "}
                  <span className="text-muted-foreground break-all">{v ? (v.match(/version (\S+?)(-|\s|$)/)?.[1] ?? v.replace(/^Blender /, "")) : "not found"}</span></span>
              </div>
            ))}
            <div className="pt-2 space-y-2">
              {queue.length === 0 && <p className="text-muted-foreground">Nothing rendering right now.</p>}
              {queue.map((j) => <JobRow key={j.id} job={j} />)}
            </div>
          </CardContent>
        </Card>
      </div>

      <h2 className="text-lg font-semibold mt-8 mb-3">Cutting shorts</h2>
      {projects.length === 0 && <Empty icon={Slice} title="No cutting videos yet">Type an object and the number of cuts, then Generate.</Empty>}
      <div className="space-y-4">
        {projects.map((p) => p.short && (
          <div key={p.id} className="space-y-2">
            <ProjectProgress projectId={p.id} />
            {p.short.status === "ready" && (
              <div className="flex gap-2">
                {PREVIEWS.map(([name, label]) => (
                  <figure key={name} className="w-20 space-y-1">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={`${API}/api/cutting/projects/${p.id}/preview/${name}`} alt={`${label} preview`} className="aspect-[9/16] w-full rounded-md object-cover bg-muted"
                      onError={(e) => (e.currentTarget.style.visibility = "hidden")} />
                    <figcaption className="text-[11px] text-muted-foreground text-center">{label}</figcaption>
                  </figure>
                ))}
              </div>
            )}
            <ShortCard short={p.short} meta={null} engine="cutting" onChanged={load} />
          </div>
        ))}
      </div>
    </>
  );
}

function ProjectProgress({ projectId }: { projectId: number }) {
  const { jobs } = useLive();
  const job = jobs.find((j) => j.project_id === projectId && j.type === "cutting" && (j.status === "running" || j.status === "queued" || j.status === "failed"));
  return job ? <JobRow job={job} showLabel={false} /> : null;
}
