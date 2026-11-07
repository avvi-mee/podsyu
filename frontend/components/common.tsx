"use client";

import { Loader2, RotateCcw, X } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api, type Job } from "@/lib/api";
import { cn } from "@/lib/utils";

export function PageHeader({ title, description, children }: { title: string; description?: string; children?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4 mb-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="text-sm text-muted-foreground mt-1">{description}</p>}
      </div>
      {children && <div className="flex flex-wrap gap-2">{children}</div>}
    </div>
  );
}

const STATUS_STYLES: Record<string, string> = {
  completed: "bg-emerald-500/15 text-emerald-400", ready: "bg-emerald-500/15 text-emerald-400",
  published: "bg-emerald-500/15 text-emerald-400", done: "bg-emerald-500/15 text-emerald-400",
  approved: "bg-emerald-500/15 text-emerald-400",
  processing: "bg-primary/20 text-yellow-300", running: "bg-primary/20 text-yellow-300",
  rendering: "bg-primary/20 text-yellow-300", uploading: "bg-primary/20 text-yellow-300",
  queued: "bg-sky-500/15 text-sky-300", pending: "bg-sky-500/15 text-sky-300", scheduled: "bg-sky-500/15 text-sky-300",
  uploaded: "bg-amber-500/15 text-amber-300", created: "bg-muted text-muted-foreground",
  failed: "bg-red-500/15 text-red-400", rejected: "bg-red-500/15 text-red-400",
  cancelled: "bg-muted text-muted-foreground",
};

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  const busy = ["processing", "running", "rendering", "uploading"].includes(status);
  return (
    <Badge variant="secondary" className={cn("capitalize gap-1 border-0", STATUS_STYLES[status] ?? "bg-muted", className)}>
      {busy && <Loader2 className="size-3 animate-spin" />}
      {status}
    </Badge>
  );
}

export function ProgressBar({ value, className }: { value: number; className?: string }) {
  return (
    <div className={cn("h-1.5 w-full rounded-full bg-muted overflow-hidden", className)}>
      <div className="h-full rounded-full bg-gradient-to-r from-primary to-emerald-400 transition-[width] duration-500" style={{ width: `${Math.round(value * 100)}%` }} />
    </div>
  );
}

const JOB_NAMES: Record<string, string> = {
  process: "Processing", render: "Rendering", recaption: "Regenerating captions", metadata: "Writing metadata",
  creator_analyze: "Analysing video", asmr: "Generating story short", media: "Media library", cutting: "Rendering cutting video",
};

export function JobRow({ job, showLabel = true }: { job: Job; showLabel?: boolean }) {
  const act = async (what: "cancel" | "retry") => {
    try {
      await api(`/api/jobs/${job.id}/${what}`, { method: "POST" });
      toast.success(what === "cancel" ? "Cancelling job" : "Job re-queued");
    } catch (e) {
      toast.error((e as Error).message);
    }
  };
  const live = job.status === "running" || job.status === "queued";
  if (job.status === "queued") // waiting jobs: one quiet line instead of a full card
    return (
      <div className="flex items-center gap-2 rounded-lg border border-dashed px-3 py-1.5 text-sm text-muted-foreground">
        <span className="truncate">{JOB_NAMES[job.type] ?? job.type}{showLabel && job.label ? ` · ${job.label}` : ""}</span>
        <span className="ml-auto shrink-0 text-xs">waiting</span>
        <Button size="icon-xs" variant="ghost" aria-label="Cancel job" onClick={() => act("cancel")}><X /></Button>
      </div>
    );
  return (
    <div className="rounded-lg border bg-card/60 p-3 space-y-2">
      <div className="flex items-center gap-2 text-sm">
        <StatusBadge status={job.status} />
        <span className="font-medium truncate">
          {JOB_NAMES[job.type] ?? job.type}
          {showLabel && job.label ? <span className="text-muted-foreground font-normal"> · {job.label}</span> : null}
        </span>
        <span className="ml-auto text-xs text-muted-foreground tabular-nums">{live ? `${Math.round(job.progress * 100)}%` : ""}</span>
        {live && (
          <Button size="icon-xs" variant="ghost" aria-label="Cancel job" onClick={() => act("cancel")}>
            <X />
          </Button>
        )}
        {(job.status === "failed" || job.status === "cancelled") && (
          <Button size="xs" variant="outline" onClick={() => act("retry")}>
            <RotateCcw /> Retry
          </Button>
        )}
      </div>
      {live && <ProgressBar value={job.progress} />}
      <p className={cn("text-xs", job.error ? "text-red-400" : "text-muted-foreground")}>
        {job.error ?? (job.stage ? `${job.stage} — ${job.message}` : job.message)}
      </p>
    </div>
  );
}

export function Empty({ icon: Icon, title, children }: { icon: React.ElementType; title: string; children?: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed p-10 text-center">
      <Icon className="mx-auto size-8 text-muted-foreground/60" />
      <p className="mt-3 font-medium">{title}</p>
      {children && <div className="mt-2 text-sm text-muted-foreground">{children}</div>}
    </div>
  );
}
