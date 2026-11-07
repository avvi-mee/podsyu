"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Check, Clapperboard, Download, SlidersHorizontal, Trash2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Empty, PageHeader } from "@/components/common";
import { ShortCard } from "@/components/short-card";
import { api, API, ENGINE_LABEL, type Options, type Project, type Short } from "@/lib/api";
import { useLiveRefresh } from "@/lib/live";

export default function ShortsPage() {
  const [shorts, setShorts] = useState<Short[] | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [meta, setMeta] = useState<Options | null>(null);
  const [filter, setFilter] = useState({ project: "", review: "", engine: "", published: "", since: "", status: "" });
  const [cutoff, setCutoff] = useState(0); // set when the date filter changes (not during render)
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [moreFilters, setMoreFilters] = useState(false);
  const extra = [filter.published, filter.since, filter.project, filter.review].filter(Boolean).length;

  const load = useCallback(() => {
    const q = new URLSearchParams();
    if (filter.project) q.set("project_id", filter.project);
    if (filter.review) q.set("review", filter.review);
    return api<Short[]>(`/api/shorts?${q}`).then(setShorts).catch((e) => toast.error(e.message));
  }, [filter]);
  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    api<Project[]>("/api/projects").then(setProjects).catch(() => {});
    api<Options>("/api/meta/options").then(setMeta).catch(() => {});
  }, []);
  useLiveRefresh(load);

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

  const all = (shorts ?? []).filter((s) => {
    const pub = s.publications?.[0]?.status;
    return (!filter.engine || (s.engine ?? "podcast") === filter.engine)
      && (!filter.status || s.status === filter.status)
      && (!filter.published || (filter.published === "yes" ? pub === "published" || pub === "uploaded" : filter.published === "scheduled" ? pub === "scheduled" || pub === "pending" : !pub))
      && (!cutoff || new Date(s.updated_at).getTime() >= cutoff);
  });
  const downloadSelected = () => {
    // one download per selected rendered short (browsers may ask to allow multiple downloads)
    all.filter((s) => selected.has(s.id) && s.status === "ready").forEach((s, i) =>
      setTimeout(() => { const a = document.createElement("a"); a.href = `${API}/api/shorts/${s.id}/download`; a.click(); }, i * 600));
  };

  return (
    <>
      <PageHeader title="Generated Shorts" description="Review, edit, approve and publish every short across your projects." />
      <div className="flex flex-wrap items-center gap-2 rounded-xl border bg-card/60 p-2.5 mb-4">
        <NativeSelect size="sm" value={filter.engine} onChange={(e) => setFilter({ ...filter, engine: e.target.value })} aria-label="Engine">
          <NativeSelectOption value="">All engines</NativeSelectOption>
          {Object.entries(ENGINE_LABEL).map(([k, v]) => <NativeSelectOption key={k} value={k}>{v}</NativeSelectOption>)}
        </NativeSelect>
        <NativeSelect size="sm" value={filter.status} onChange={(e) => setFilter({ ...filter, status: e.target.value })} aria-label="Processing status">
          <NativeSelectOption value="">Any status</NativeSelectOption>
          {["ready", "candidate", "rendering", "pending", "failed"].map((v) => <NativeSelectOption key={v} value={v}>{v}</NativeSelectOption>)}
        </NativeSelect>
        <Button size="sm" variant={extra ? "secondary" : "ghost"} onClick={() => setMoreFilters(!moreFilters)}>
          <SlidersHorizontal /> More filters{extra ? ` (${extra})` : ""}
        </Button>
        {moreFilters && (
          <div className="w-full flex flex-wrap items-center gap-2 order-last border-t pt-2">
            <NativeSelect size="sm" value={filter.published} onChange={(e) => setFilter({ ...filter, published: e.target.value })} aria-label="Published">
              <NativeSelectOption value="">Published or not</NativeSelectOption>
              <NativeSelectOption value="yes">Published / uploaded</NativeSelectOption>
              <NativeSelectOption value="scheduled">Scheduled</NativeSelectOption>
              <NativeSelectOption value="no">Not published</NativeSelectOption>
            </NativeSelect>
            <NativeSelect size="sm" value={filter.since} onChange={(e) => { setFilter({ ...filter, since: e.target.value }); setCutoff(e.target.value ? Date.now() - Number(e.target.value) * 86400000 : 0); }} aria-label="Date">
              <NativeSelectOption value="">Any date</NativeSelectOption>
              <NativeSelectOption value="1">Last 24 hours</NativeSelectOption>
              <NativeSelectOption value="7">Last 7 days</NativeSelectOption>
              <NativeSelectOption value="30">Last 30 days</NativeSelectOption>
            </NativeSelect>
            <NativeSelect size="sm" value={filter.project} onChange={(e) => setFilter({ ...filter, project: e.target.value })} aria-label="Project">
              <NativeSelectOption value="">All projects</NativeSelectOption>
              {projects.map((p) => <NativeSelectOption key={p.id} value={p.id}>{p.title.slice(0, 60)}</NativeSelectOption>)}
            </NativeSelect>
            <NativeSelect size="sm" value={filter.review} onChange={(e) => setFilter({ ...filter, review: e.target.value })} aria-label="Review state">
              <NativeSelectOption value="">Any review state</NativeSelectOption>
              <NativeSelectOption value="none">Not reviewed</NativeSelectOption>
              <NativeSelectOption value="approved">Approved</NativeSelectOption>
              <NativeSelectOption value="rejected">Rejected</NativeSelectOption>
            </NativeSelect>
          </div>
        )}
        <span className="mx-1 h-5 w-px bg-border" />
        <Button size="sm" variant="ghost" onClick={() => setSelected(selected.size === all.length ? new Set() : new Set(all.map((s) => s.id)))}>
          {selected.size === all.length && all.length ? "Clear" : "Select all"}
        </Button>
        {selected.size > 0 && (
          <>
            <span className="text-xs text-muted-foreground">{selected.size} selected</span>
            <Button size="sm" variant="outline" onClick={() => bulk("approve")}><Check className="text-emerald-400" /> Approve</Button>
            <Button size="sm" variant="outline" onClick={() => bulk("reject")}><X className="text-red-400" /> Reject</Button>
            <Button size="sm" variant="outline" onClick={downloadSelected}><Download /> Download</Button>
            <Button size="sm" variant="ghost" onClick={() => bulk("delete")}><Trash2 /> Delete</Button>
          </>
        )}
      </div>
      {shorts?.length === 0 && <Empty icon={Clapperboard} title="No shorts match">Generate shorts with the Podcast, Famous Creators or ASMR engines.</Empty>}
      <div className="space-y-4">
        {all.map((s) => (
          <div key={s.id}>
            <p className="text-xs text-muted-foreground mb-1.5 truncate">{s.project_title}</p>
            <ShortCard short={s} meta={meta} selected={selected.has(s.id)}
              onSelect={(v) => setSelected((cur) => { const n = new Set(cur); if (v) n.add(s.id); else n.delete(s.id); return n; })}
              onChanged={load} />
          </div>
        ))}
      </div>
    </>
  );
}
