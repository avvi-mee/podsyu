"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { CalendarClock, ChevronLeft, ChevronRight, ExternalLink, Info, RotateCcw, Trash2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { PageHeader, ProgressBar, StatusBadge } from "@/components/common";
import { api, fmtDate, type Publication } from "@/lib/api";
import { useLive, useLiveRefresh } from "@/lib/live";
import { cn } from "@/lib/utils";

const DOT: Record<string, string> = {
  published: "bg-emerald-400", uploaded: "bg-amber-400", scheduled: "bg-sky-400", pending: "bg-sky-400",
  uploading: "bg-primary", failed: "bg-red-500", cancelled: "bg-muted-foreground",
};
const dayKey = (iso: string, tz: string) => new Intl.DateTimeFormat("en-CA", { timeZone: tz }).format(new Date(iso));
const localInput = (iso: string, tz: string) => {
  const p = Object.fromEntries(new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(new Date(iso)).map((x) => [x.type, x.value]));
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`;
};

// Suspense: the calendar depends on "now", so it renders on the client instead of at build time.
export default function CalendarPage() {
  return (
    <Suspense>
      <CalendarView />
    </Suspense>
  );
}

function CalendarView() {
  const [pubs, setPubs] = useState<Publication[]>([]);
  const [tz, setTz] = useState("Asia/Kolkata");
  const [month, setMonth] = useState(() => { const d = new Date(); return { y: d.getFullYear(), m: d.getMonth() }; });
  const [open, setOpen] = useState<Publication | null>(null);
  const live = useLive();

  const load = useCallback(() => api<Publication[]>("/api/publications").then(setPubs).catch((e) => toast.error(e.message)), []);
  useEffect(() => {
    load();
    api<{ settings: { timezone: string } }>("/api/settings").then((s) => setTz(s.settings.timezone)).catch(() => {});
  }, [load]);
  useLiveRefresh(load);

  // live upload progress overrides
  const merged = pubs.map((p) => live.publications.find((x) => x.id === p.id) ? { ...p, ...live.publications.find((x) => x.id === p.id) } : p);
  const byDay: Record<string, Publication[]> = {};
  for (const p of merged) (byDay[dayKey(p.publish_at ?? p.created_at, tz)] ??= []).push(p);

  const first = new Date(month.y, month.m, 1);
  const startPad = (first.getDay() + 6) % 7; // Monday first
  const days = new Date(month.y, month.m + 1, 0).getDate();
  const cells = [...Array(startPad).fill(null), ...Array.from({ length: days }, (_, i) => i + 1)];
  const todayKey = dayKey(new Date().toISOString(), tz);
  const upcoming = merged.filter((p) => ["pending", "uploading", "scheduled"].includes(p.status))
    .sort((a, b) => (a.publish_at ?? a.created_at).localeCompare(b.publish_at ?? b.created_at));

  return (
    <>
      <PageHeader title="Publishing Calendar" description={`All times shown in ${tz} (change in Settings).`} />
      <div className="mb-4 flex gap-2 rounded-xl border border-sky-500/30 bg-sky-500/10 p-3 text-sm">
        <Info className="size-4 mt-0.5 shrink-0 text-sky-300" />
        <span><b>Schedule on YouTube</b> uploads right away and YouTube publishes at the set time, so your PC can be off. <b>Schedule upload (this app)</b> is handled by this app&apos;s local scheduler: your computer and the app must be running at the scheduled time.</span>
      </div>
      <div className="grid xl:grid-cols-[1fr_340px] gap-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>{first.toLocaleString("en", { month: "long", year: "numeric" })}</CardTitle>
            <div className="flex gap-1">
              <Button size="icon-sm" variant="outline" aria-label="Previous month" onClick={() => setMonth(({ y, m }) => (m ? { y, m: m - 1 } : { y: y - 1, m: 11 }))}><ChevronLeft /></Button>
              <Button size="sm" variant="outline" onClick={() => { const d = new Date(); setMonth({ y: d.getFullYear(), m: d.getMonth() }); }}>Today</Button>
              <Button size="icon-sm" variant="outline" aria-label="Next month" onClick={() => setMonth(({ y, m }) => (m === 11 ? { y: y + 1, m: 0 } : { y, m: m + 1 }))}><ChevronRight /></Button>
            </div>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-7 text-xs text-muted-foreground mb-1">
              {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => <div key={d} className="px-1.5 py-1">{d}</div>)}
            </div>
            <div className="grid grid-cols-7 gap-1">
              {cells.map((d, i) => {
                const key = d ? `${month.y}-${String(month.m + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}` : "";
                const items = d ? byDay[key] ?? [] : [];
                return (
                  <div key={i} className={cn("min-h-24 rounded-lg p-1.5 text-xs", d ? "bg-muted/30" : "", key === todayKey && "ring-1 ring-primary")}>
                    {d && <div className={cn("mb-1 tabular-nums", key === todayKey ? "text-primary font-semibold" : "text-muted-foreground")}>{d}</div>}
                    <div className="space-y-1">
                      {items.slice(0, 4).map((p) => (
                        <button key={p.id} onClick={() => setOpen(p)} className="w-full flex items-center gap-1 rounded bg-card px-1 py-0.5 text-left hover:bg-accent truncate">
                          <span className={cn("size-1.5 shrink-0 rounded-full", DOT[p.status] ?? "bg-muted")} />
                          <span className="truncate">{p.short_title || p.title}</span>
                        </button>
                      ))}
                      {items.length > 4 && <div className="text-muted-foreground">+{items.length - 4} more</div>}
                    </div>
                  </div>
                );
              })}
            </div>
            <div className="mt-3 flex flex-wrap gap-3 text-xs text-muted-foreground">
              {["scheduled", "uploading", "published", "uploaded", "failed"].map((s) => (
                <span key={s} className="flex items-center gap-1.5 capitalize"><span className={cn("size-2 rounded-full", DOT[s])} />{s}</span>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle className="flex items-center gap-2"><CalendarClock className="size-4 text-primary" /> Upcoming queue</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            {upcoming.length === 0 && <p className="text-sm text-muted-foreground">Nothing scheduled. Publish a short from the Generated Shorts page.</p>}
            {upcoming.map((p) => (
              <button key={p.id} onClick={() => setOpen(p)} className="w-full text-left rounded-lg border p-3 hover:bg-muted/40 space-y-1.5">
                <div className="flex items-center gap-2"><StatusBadge status={p.status} /><span className="text-sm truncate">{p.title}</span></div>
                <div className="text-xs text-muted-foreground">{p.publish_at ? fmtDate(p.publish_at, tz) : "Now"} · {p.channel_title}{p.mode === "local" ? " · app-managed" : p.mode === "youtube" ? " · YouTube-managed" : ""}</div>
                {p.status === "uploading" && <ProgressBar value={p.progress} />}
              </button>
            ))}
            {merged.filter((p) => p.status === "failed").map((p) => (
              <button key={p.id} onClick={() => setOpen(p)} className="w-full text-left rounded-lg border border-red-500/30 p-3 hover:bg-muted/40 space-y-1">
                <div className="flex items-center gap-2"><StatusBadge status="failed" /><span className="text-sm truncate">{p.title}</span></div>
                <p className="text-xs text-red-400 line-clamp-2">{p.error}</p>
              </button>
            ))}
          </CardContent>
        </Card>
      </div>
      {open && <PubDialog pub={merged.find((p) => p.id === open.id) ?? open} tz={tz} onClose={() => setOpen(null)} onChanged={load} />}
    </>
  );
}

function PubDialog({ pub, tz, onClose, onChanged }: { pub: Publication; tz: string; onClose: () => void; onChanged: () => void }) {
  const [at, setAt] = useState(pub.publish_at ? localInput(pub.publish_at, tz) : "");
  const act = async (fn: () => Promise<unknown>, ok: string) => {
    try {
      await fn();
      toast.success(ok);
      onChanged();
      onClose();
    } catch (e) {
      toast.error((e as Error).message);
    }
  };
  const canReschedule = pub.status === "pending" || pub.status === "failed" || (pub.status === "scheduled" && !!pub.youtube_video_id);
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="pr-6">{pub.title}</DialogTitle>
          <DialogDescription>{pub.channel_title} · {pub.privacy} · {pub.mode === "now" ? "publish now" : pub.mode === "youtube" ? "YouTube-managed schedule" : "app-managed schedule"}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3 text-sm">
          <div className="flex items-center gap-2"><StatusBadge status={pub.status} />{pub.publish_at && <span className="text-muted-foreground">{fmtDate(pub.publish_at, tz)}</span>}</div>
          {pub.status === "uploading" && <ProgressBar value={pub.progress} />}
          {pub.message && <p className="text-muted-foreground">{pub.message}</p>}
          {pub.error && <p className="text-red-400">{pub.error}</p>}
          {pub.youtube_video_id && (
            <a className="inline-flex items-center gap-1 text-primary hover:underline" href={`https://studio.youtube.com/video/${pub.youtube_video_id}/edit`} target="_blank" rel="noreferrer">
              Open in YouTube Studio <ExternalLink className="size-3" />
            </a>
          )}
          {canReschedule && (
            <div className="space-y-1.5 pt-2">
              <label className="text-xs text-muted-foreground">Reschedule ({tz})</label>
              <div className="flex gap-2">
                <Input type="datetime-local" value={at} onChange={(e) => setAt(e.target.value)} />
                <Button disabled={!at} onClick={() => act(() => api(`/api/publications/${pub.id}`, { method: "PATCH", json: { publish_at: at, timezone: tz } }), "Rescheduled")}>Save</Button>
              </div>
            </div>
          )}
          <div className="flex flex-wrap gap-2 pt-2">
            {pub.status === "failed" && (
              <Button variant="outline" onClick={() => act(() => api(`/api/publications/${pub.id}/retry`, { method: "POST" }), "Retrying upload")}><RotateCcw /> Retry upload</Button>
            )}
            {pub.status !== "uploading" && (
              <Button variant="ghost" onClick={() => confirm(pub.status === "scheduled" ? "Cancel this schedule? The video stays private on YouTube." : "Remove this entry?") &&
                act(() => api(`/api/publications/${pub.id}`, { method: "DELETE" }), pub.status === "scheduled" ? "Schedule cancelled" : "Removed")}>
                <Trash2 /> {pub.status === "scheduled" ? "Cancel schedule" : pub.status === "pending" ? "Delete scheduled task" : "Remove from history"}
              </Button>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
