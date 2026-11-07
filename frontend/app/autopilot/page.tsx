"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { CalendarClock, Loader2, Rocket, Send } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Empty, PageHeader, ProgressBar, StatusBadge } from "@/components/common";
import { api, type Account, type Project } from "@/lib/api";
import { useLive, useLiveRefresh } from "@/lib/live";
import { cn } from "@/lib/utils";

const LENGTHS: Record<string, [number, number]> = { "15-30": [15, 30], "30-60": [30, 60], "45-90": [45, 90] };
const EVERY = [4, 6, 8, 12, 24, 48];
const everyLabel = (h: number) => (h < 24 ? h + " hours" : h === 24 ? "day" : "2 days");
type Mode = "now" | "schedule" | "skip";
type Row = { mode: Mode; at: string };

/** datetime-local value (local time) for a Date */
const toLocal = (d: Date) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
/** Today 6 PM, or tomorrow if that is under an hour away */
function nextEvening() {
  const d = new Date();
  d.setHours(18, 0, 0, 0);
  if (d.getTime() < Date.now() + 3600e3) d.setDate(d.getDate() + 1);
  return toLocal(d);
}

export default function AutopilotPage() {
  const [accounts, setAccounts] = useState<Account[] | null>(null);
  const [tz, setTz] = useState("");
  const [runs, setRuns] = useState<Project[]>([]);
  const [busy, setBusy] = useState(false);
  const [f, setF] = useState({ url: "", length: "30-60", clips: 5, account_id: "", authorized: false });
  // step 2: when each clip goes out (row i = i-th best clip)
  const [planOpen, setPlanOpen] = useState(false);
  const [plan, setPlan] = useState<Row[]>([]);
  const [fill, setFill] = useState({ from: "", every: 24 });
  const { jobs } = useLive();

  const loadRuns = useCallback(
    () => api<Project[]>("/api/projects").then((ps) => setRuns(ps.filter((p) => p.options?.autopilot))).catch(() => {}),
    [],
  );
  useEffect(() => {
    loadRuns();
    api<Account[]>("/api/youtube/accounts")
      .then((a) => { setAccounts(a); setF((x) => ({ ...x, account_id: x.account_id || String(a[0]?.id ?? "") })); })
      .catch((e) => toast.error(e.message));
    api<{ settings: Record<string, string> }>("/api/settings").then(({ settings: s }) => setTz(s.timezone)).catch(() => {});
  }, [loadRuns]);
  useLiveRefresh(loadRuns);

  const scheduleAll = (from: string, every: number, n: number) =>
    Array.from({ length: n }, (_, k) => ({ mode: "schedule" as Mode, at: toLocal(new Date(new Date(from).getTime() + k * every * 3600e3)) }));

  const openPlan = () => {
    const from = fill.from || nextEvening();
    setFill({ ...fill, from });
    // keep earlier choices when reopening; new rows default to the daily schedule
    setPlan((old) => scheduleAll(from, fill.every, f.clips).map((r, i) => old[i] ?? r));
    setPlanOpen(true);
  };
  const setRow = (i: number, r: Partial<Row>) => setPlan((p) => p.map((x, k) => (k === i ? { ...x, ...r } : x)));

  const formErr = !f.url.trim() ? "Paste a YouTube link"
    : !f.account_id ? "Connect / pick a YouTube channel"
    : !f.authorized ? "Confirm you own the video or have permission" : "";
  const planErr = plan.some((r) => r.mode === "schedule" && !r.at) ? "Set a time for every scheduled clip"
    : plan.every((r) => r.mode === "skip") ? "Choose at least one clip to post" : "";
  const count = (m: Mode) => plan.filter((r) => r.mode === m).length;

  const start = async () => {
    setBusy(true);
    const [min, max] = LENGTHS[f.length];
    try {
      await api("/api/projects/youtube", {
        method: "POST",
        json: {
          url: f.url.trim(), authorized: f.authorized,
          options: { min_duration: min, max_duration: max, num_shorts: f.clips, autopilot: { enabled: true, account_id: Number(f.account_id), plan } },
        },
      });
      toast.success("Autopilot started - each clip will post by your plan");
      setPlanOpen(false);
      setPlan([]);
      setF((x) => ({ ...x, url: "", authorized: false }));
      loadRuns();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader title="Autopilot" description="Paste a link, fill the form, choose when each clip goes out. It makes the shorts and posts them by itself - no approval needed." />
      <div className="grid lg:grid-cols-5 gap-4">
        <Card className="lg:col-span-3">
          <CardContent className="space-y-4">
            <Field label="YouTube link">
              <Input placeholder="https://www.youtube.com/watch?v=..." value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} />
            </Field>
            <div className="grid sm:grid-cols-3 gap-3">
              <Field label="Clip length">
                <NativeSelect className="w-full" value={f.length} onChange={(e) => setF({ ...f, length: e.target.value })}>
                  {Object.keys(LENGTHS).map((k) => <NativeSelectOption key={k} value={k}>{k.replace("-", "–")} seconds</NativeSelectOption>)}
                </NativeSelect>
              </Field>
              <Field label="Shorts to make">
                <Input type="number" min={1} max={30} value={f.clips} onChange={(e) => setF({ ...f, clips: Math.max(1, Math.min(30, +e.target.value || 1)) })} />
              </Field>
              <Field label="YouTube channel">
                {accounts && accounts.length === 0 ? (
                  <p className="text-sm text-amber-300 pt-2"><Link href="/accounts" className="underline">Connect your channel</Link> first.</p>
                ) : (
                  <NativeSelect className="w-full" value={f.account_id} onChange={(e) => setF({ ...f, account_id: e.target.value })}>
                    {(accounts ?? []).map((a) => <NativeSelectOption key={a.id} value={a.id}>{a.channel_title}</NativeSelectOption>)}
                  </NativeSelect>
                )}
              </Field>
            </div>
            <label className="flex items-start gap-3 rounded-lg border p-3 text-sm cursor-pointer">
              <Checkbox checked={f.authorized} onCheckedChange={(v) => setF({ ...f, authorized: v === true })} className="mt-0.5" />
              <span>I own this video or have permission from the rights holder to download, edit and republish it.</span>
            </label>
            <Button size="lg" className="w-full h-11" disabled={!!formErr} onClick={openPlan}>
              <CalendarClock /> Next: choose when to post each clip
            </Button>
            {formErr && <p className="text-xs text-muted-foreground text-center">{formErr}</p>}
            <p className="text-xs text-muted-foreground">
              Uses your default caption style (Settings). Scheduled clips upload as private right after rendering and YouTube makes them public on time,
              even if this PC is off. YouTube&apos;s free API allows about 6 uploads a day; extra ones upload after the daily reset (keep the app running).
            </p>
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Autopilot runs</CardTitle>
            <CardDescription>Updates live. Scheduled posts also show in the Publishing Calendar.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {runs.length === 0 && <Empty icon={Rocket} title="No runs yet" />}
            {runs.map((p) => {
              const ap = p.options.autopilot as { status: string; message: string };
              const job = jobs.find((j) => j.project_id === p.id && (j.status === "running" || j.status === "queued"));
              return (
                <Link key={p.id} href={`/projects/${p.id}`} className="block rounded-lg border p-3 space-y-1.5 hover:bg-muted/40 transition-colors">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-sm font-medium flex-1">{p.title}</span>
                    <StatusBadge status={ap.status === "waiting" ? p.status : ap.status} />
                  </div>
                  {job && <><ProgressBar value={job.progress} /><p className="text-xs text-muted-foreground">{job.stage || "queued"} - {job.message}</p></>}
                  <p className={ap.status === "failed" || p.status === "failed" ? "text-xs text-red-400" : "text-xs text-muted-foreground"}>
                    {p.status === "failed" ? p.error : ap.message}
                  </p>
                </Link>
              );
            })}
          </CardContent>
        </Card>
      </div>

      <Dialog open={planOpen} onOpenChange={setPlanOpen}>
        <DialogContent className="sm:max-w-xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>When should each clip go out?</DialogTitle>
            <DialogDescription>
              The AI ranks the clips after processing - Clip 1 is the best. After this, everything runs by itself.{tz ? ` Times are ${tz}.` : ""}
            </DialogDescription>
          </DialogHeader>

          <div className="flex flex-wrap items-end gap-2 rounded-lg border bg-muted/30 p-3">
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Schedule all from</Label>
              <Input type="datetime-local" value={fill.from} onChange={(e) => setFill({ ...fill, from: e.target.value })} />
            </div>
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">one every</Label>
              <NativeSelect value={fill.every} onChange={(e) => setFill({ ...fill, every: +e.target.value })}>
                {EVERY.map((h) => <NativeSelectOption key={h} value={h}>{everyLabel(h)}</NativeSelectOption>)}
              </NativeSelect>
            </div>
            <Button variant="outline" disabled={!fill.from} onClick={() => setPlan(scheduleAll(fill.from, fill.every, plan.length))}>Apply</Button>
            <Button variant="ghost" onClick={() => setPlan((p) => p.map((r) => ({ ...r, mode: "now" })))}><Send /> Post all now</Button>
          </div>

          <div className="space-y-2">
            {plan.map((r, i) => (
              <div key={i} className="flex flex-wrap items-center gap-2 rounded-lg border p-2">
                <span className="w-24 text-sm font-medium">Clip {i + 1}{i === 0 && <span className="text-xs text-primary"> · best</span>}</span>
                <div className="flex rounded-md border p-0.5">
                  {([["now", "Post now"], ["schedule", "Schedule"], ["skip", "Don't post"]] as const).map(([m, label]) => (
                    <button key={m} type="button" onClick={() => setRow(i, { mode: m })}
                      className={cn("rounded px-2.5 py-1 text-xs", r.mode === m ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground")}>
                      {label}
                    </button>
                  ))}
                </div>
                {r.mode === "schedule" && (
                  <Input type="datetime-local" className="w-auto flex-1 min-w-48" value={r.at} onChange={(e) => setRow(i, { at: e.target.value })} aria-label={`Clip ${i + 1} time`} />
                )}
                {r.mode === "now" && <span className="text-xs text-muted-foreground">as soon as it&apos;s ready</span>}
              </div>
            ))}
          </div>

          <DialogFooter className="items-center gap-2">
            <span className="mr-auto text-xs text-muted-foreground">
              {planErr || `${count("now")} post now · ${count("schedule")} scheduled · ${count("skip")} not posted`}
            </span>
            <Button variant="ghost" onClick={() => setPlanOpen(false)}>Back</Button>
            <Button disabled={!!planErr || busy} onClick={start}>
              {busy ? <Loader2 className="animate-spin" /> : <Rocket />} Start autopilot
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
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
