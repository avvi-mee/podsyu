"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { FolderOpen, PlusCircle, Trash2, MonitorPlay, FileVideo } from "lucide-react";
import { toast } from "sonner";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Empty, PageHeader, StatusBadge } from "@/components/common";
import { api, API, ENGINE_LABEL, fmtDate, fmtTime, type Project } from "@/lib/api";
import { useLiveRefresh } from "@/lib/live";

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const load = useCallback(() => api<Project[]>("/api/projects").then(setProjects).catch((e) => toast.error(e.message)), []);
  useEffect(() => {
    load();
  }, [load]);
  useLiveRefresh(load);

  const remove = async (p: Project) => {
    if (!confirm(`Delete "${p.title}" with all its shorts and files?`)) return;
    try {
      await api(`/api/projects/${p.id}`, { method: "DELETE" });
      toast.success("Project deleted");
      load();
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  return (
    <>
      <PageHeader title="My Projects" description="Every imported podcast is a project. Reopen one any time - nothing is re-processed.">
        <Button render={<Link href="/create" />} nativeButton={false}><PlusCircle /> New project</Button>
      </PageHeader>
      {projects?.length === 0 && <Empty icon={FolderOpen} title="No projects yet">Create your first project from a YouTube URL or a local video.</Empty>}
      <div className="grid sm:grid-cols-2 xl:grid-cols-3 gap-4">
        {projects?.map((p) => (
          <Card key={p.id} className="p-0 gap-0 overflow-hidden lift">
            <Link href={`/projects/${p.id}`} className="block">
              <div className="relative aspect-video bg-muted">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={`${API}/api/projects/${p.id}/thumbnail`} alt="" className="size-full object-cover" onError={(e) => (e.currentTarget.style.visibility = "hidden")} />
                <div className="absolute top-2 left-2 flex gap-1"><StatusBadge status={p.status} /><span className="rounded-md bg-black/70 px-1.5 py-0.5 text-[11px]">{ENGINE_LABEL[p.engine ?? "podcast"]}</span></div>
                <span className="absolute bottom-2 right-2 rounded bg-black/75 px-1.5 py-0.5 text-xs tabular-nums">{fmtTime(p.duration)}</span>
              </div>
            </Link>
            <div className="p-4 space-y-2">
              <Link href={`/projects/${p.id}`} className="font-medium leading-snug line-clamp-2 hover:text-primary">{p.title}</Link>
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                {p.source_type === "youtube" ? <MonitorPlay className="size-3.5" /> : <FileVideo className="size-3.5" />}
                <span className="truncate">{p.channel ?? (p.source_type === "local" ? "Local file" : "")}</span>
                <span className="ml-auto whitespace-nowrap">{fmtDate(p.created_at, undefined, false)}</span>
              </div>
              <div className="flex items-center justify-between pt-1">
                <span className="text-sm"><span className="text-emerald-400 font-medium">{p.shorts_ready}</span><span className="text-muted-foreground"> / {p.shorts_total} shorts ready</span></span>
                <Button size="icon-sm" variant="ghost" aria-label="Delete project" onClick={() => remove(p)}><Trash2 /></Button>
              </div>
              {p.error && <p className="text-xs text-red-400 line-clamp-2">{p.error}</p>}
            </div>
          </Card>
        ))}
      </div>
    </>
  );
}
