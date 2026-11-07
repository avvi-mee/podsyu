"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Activity, FolderOpen, Gamepad2, Mic, Moon, Rocket, Slice } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Empty, JobRow, PageHeader, StatusBadge } from "@/components/common";
import { api, API, fmtDate, fmtTime, type Project } from "@/lib/api";
import { useLive, useLiveRefresh } from "@/lib/live";

type Stats = {
  videos_processed: number; projects: number; shorts_generated: number; ready_to_publish: number; published: number;
  scheduled: number; failed_uploads: number; recent_projects: Project[]; by_engine: Record<string, number>;
};

export default function Overview() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState("");
  const { jobs } = useLive();
  const load = useCallback(() => api<Stats>("/api/stats").then(setStats).catch((e) => setError(e.message)), []);
  useEffect(() => {
    load();
  }, [load]);
  useLiveRefresh(load);

  const byEngine = stats?.by_engine ?? {};
  const cards = [
    { label: "Ready to publish", value: stats?.ready_to_publish, href: "/shorts" },
    { label: "Published", value: stats?.published, href: "/calendar" },
    { label: "Scheduled", value: stats?.scheduled, href: "/calendar" },
    {
      label: "Shorts made", value: stats?.shorts_generated, href: "/shorts",
      sub: stats ? `${byEngine.podcast ?? 0} podcast · ${byEngine.creator ?? 0} creator · ${byEngine.asmr ?? 0} story · ${byEngine.cutting ?? 0} cutting` : "",
    },
  ];
  const queue = jobs.filter((j) => j.status === "running" || j.status === "queued");
  const failed = jobs.filter((j) => j.status === "failed").slice(0, 3);

  return (
    <>
      <PageHeader title="Dashboard">
        <Button render={<Link href="/autopilot" />} nativeButton={false}><Rocket /> Autopilot</Button>
        <Button variant="outline" render={<Link href="/create" />} nativeButton={false}><Mic /> Podcast clips</Button>
        <Button variant="outline" render={<Link href="/creators" />} nativeButton={false}><Gamepad2 /> Creator clips</Button>
        <Button variant="outline" render={<Link href="/asmr" />} nativeButton={false}><Moon /> Story short</Button>
        <Button variant="outline" render={<Link href="/cutting" />} nativeButton={false}><Slice /> Cutting short</Button>
      </PageHeader>
      {error && <p className="mb-4 text-sm text-red-400">{error}</p>}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
        {cards.map(({ label, value, href, sub }) => (
          <Link key={label} href={href}>
            <Card className="lift h-full">
              <CardContent className="pt-1">
                <div className="text-3xl font-semibold tabular-nums">{value ?? "–"}</div>
                <div className="text-sm text-muted-foreground mt-1">{label}</div>
                {sub && <div className="text-[11px] text-muted-foreground/70 mt-0.5">{sub}</div>}
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>

      <div className="grid lg:grid-cols-5 gap-4">
        <Card className="lg:col-span-3">
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><FolderOpen className="size-4 text-primary" /> Recent projects</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {stats && stats.recent_projects.length === 0 && (
              <Empty icon={FolderOpen} title="No projects yet">
                Import a podcast from YouTube or upload a video file to get started.
              </Empty>
            )}
            {stats?.recent_projects.slice(0, 5).map((p) => (
              <Link key={p.id} href={`/projects/${p.id}`} className="flex items-center gap-3 rounded-lg p-2 -mx-2 hover:bg-muted/50 transition-colors">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={`${API}/api/projects/${p.id}/thumbnail`} alt="" className="w-24 aspect-video rounded-md object-cover bg-muted" onError={(e) => (e.currentTarget.style.visibility = "hidden")} />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{p.title}</div>
                  <div className="text-xs text-muted-foreground">{fmtTime(p.duration)} · {fmtDate(p.created_at, undefined, false)}</div>
                </div>
                <StatusBadge status={p.status} />
              </Link>
            ))}
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><Activity className="size-4 text-primary" /> Queue{queue.length ? ` (${queue.length})` : ""}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {queue.length === 0 && <p className="text-sm text-muted-foreground">Nothing processing right now.</p>}
            {queue.filter((j) => j.status === "running").map((j) => <JobRow key={j.id} job={j} />)}
            {queue.filter((j) => j.status === "queued").slice(0, 3).map((j) => <JobRow key={j.id} job={j} />)}
            {queue.filter((j) => j.status === "queued").length > 3 && (
              <p className="text-xs text-muted-foreground px-1">+ {queue.filter((j) => j.status === "queued").length - 3} more waiting</p>
            )}
            {failed.map((j) => <JobRow key={j.id} job={j} />)}
            {(stats?.failed_uploads ?? 0) > 0 && (
              <Link href="/calendar" className="block text-sm text-red-400 hover:underline pt-2">
                {stats?.failed_uploads} failed upload(s) — open the calendar to retry
              </Link>
            )}
          </CardContent>
        </Card>
      </div>
    </>
  );
}
