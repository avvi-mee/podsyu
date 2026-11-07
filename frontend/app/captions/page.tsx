"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Check, Palette, Save, Star, Trash2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { PageHeader } from "@/components/common";
import { CaptionEditor, CaptionPreview, presetStyle } from "@/components/caption-editor";
import { api, type CaptionStyle, type Options, type Project, type Short } from "@/lib/api";
import { cn } from "@/lib/utils";

type Custom = { id: number; name: string; style: CaptionStyle };

export default function CaptionsPage() {
  const [meta, setMeta] = useState<Options | null>(null);
  const [custom, setCustom] = useState<Custom[]>([]);
  const [def, setDef] = useState("hormozi");
  const [style, setStyle] = useState<CaptionStyle | null>(null);
  const [editing, setEditing] = useState<{ id?: number; name: string }>({ name: "" });
  const [shorts, setShorts] = useState<Short[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [previewOn, setPreviewOn] = useState<number | undefined>();
  const [target, setTarget] = useState("");

  const load = useCallback(() => api<{ custom: Custom[]; default: string }>("/api/caption-templates").then((t) => { setCustom(t.custom); setDef(t.default); }), []);
  useEffect(() => {
    api<Options>("/api/meta/options").then((m) => { setMeta(m); setStyle(presetStyle(m, "hormozi")); }).catch((e) => toast.error(e.message));
    load().catch(() => {});
    api<Short[]>("/api/shorts?status=ready").then((s) => setShorts(s.filter((x) => x.source_available).slice(0, 30))).catch(() => {});
    api<Project[]>("/api/projects").then(setProjects).catch(() => {});
  }, [load]);

  const guard = async (fn: () => Promise<unknown>, ok: string) => {
    try {
      await fn();
      toast.success(ok);
      load();
    } catch (e) {
      toast.error((e as Error).message);
    }
  };
  if (!meta || !style) return null;

  return (
    <>
      <PageHeader title="Caption Templates" description="Burned-in, word-synced captions. Pick a preset, tweak it, and save your own templates." />
      <div className="grid lg:grid-cols-[240px_1fr_300px] gap-4">
        <Card>
          <CardHeader><CardTitle>Presets</CardTitle></CardHeader>
          <CardContent className="space-y-1">
            {Object.entries(meta.presets).map(([k, p]) => (
              <button key={k} onClick={() => { setStyle(presetStyle(meta, k)); setEditing({ name: "" }); }}
                className={cn("w-full flex items-center justify-between rounded-lg px-3 py-2 text-sm text-left hover:bg-muted/60", style.preset === k && !editing.id && "bg-accent")}>
                <span>{p.name}</span>
                {def === k && <Star className="size-3.5 fill-amber-400 text-amber-400" aria-label="Default preset" />}
              </button>
            ))}
            {custom.length > 0 && <p className="pt-3 pb-1 text-xs uppercase tracking-wide text-muted-foreground">My templates</p>}
            {custom.map((t) => (
              <div key={t.id} className={cn("flex items-center rounded-lg hover:bg-muted/60", editing.id === t.id && "bg-accent")}>
                <button className="flex-1 px-3 py-2 text-sm text-left truncate" onClick={() => { setStyle(t.style); setEditing({ id: t.id, name: t.name }); }}>{t.name}</button>
                <Button size="icon-xs" variant="ghost" aria-label={`Delete ${t.name}`} onClick={() => confirm(`Delete template "${t.name}"?`) && guard(() => api(`/api/caption-templates/${t.id}`, { method: "DELETE" }), "Template deleted")}><Trash2 /></Button>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Customize</CardTitle></CardHeader>
          <CardContent className="space-y-5">
            <CaptionEditor style={style} onChange={setStyle} meta={meta} />
            <div className="flex flex-wrap gap-2 border-t pt-4">
              <Input className="w-48" placeholder="Template name" value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })} />
              <Button disabled={!editing.name.trim()} onClick={() => guard(() => api("/api/caption-templates", { method: "POST", json: { id: editing.id, name: editing.name, style } }), editing.id ? "Template updated" : "Template saved")}>
                <Save /> {editing.id ? "Update template" : "Save as template"}
              </Button>
              {style.preset && meta.presets[style.preset] && def !== style.preset && !editing.id && (
                <Button variant="outline" onClick={() => guard(() => api("/api/settings", { method: "PUT", json: { default_caption_preset: style.preset } }), "Default preset updated")}>
                  <Star /> Make {meta.presets[style.preset].name} the default
                </Button>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-2 border-t pt-4">
              <NativeSelect value={target} onChange={(e) => setTarget(e.target.value)} aria-label="Project to apply to">
                <NativeSelectOption value="">Apply this style to a project...</NativeSelectOption>
                {projects.map((p) => <NativeSelectOption key={p.id} value={p.id}>{p.title.slice(0, 50)}</NativeSelectOption>)}
              </NativeSelect>
              <Button variant="outline" disabled={!target} onClick={() => guard(async () => {
                const r = await api<{ queued: number }>(`/api/projects/${target}/caption-style`, { method: "PUT", json: { style } });
                toast.info(`Re-rendering ${r.queued} short(s)`);
              }, "Applied to all shorts in the project")}>
                <Palette /> Apply to all shorts
              </Button>
            </div>
          </CardContent>
        </Card>

        <div className="space-y-3">
          <CaptionPreview style={style} shortId={previewOn} />
          <NativeSelect className="w-full" value={previewOn ?? ""} onChange={(e) => setPreviewOn(e.target.value ? +e.target.value : undefined)} aria-label="Preview background">
            <NativeSelectOption value="">Preview on sample background</NativeSelectOption>
            {shorts.map((s) => <NativeSelectOption key={s.id} value={s.id}>{s.title.slice(0, 50)}</NativeSelectOption>)}
          </NativeSelect>
          <p className="text-xs text-muted-foreground flex gap-1.5"><Check className="size-3.5 text-emerald-400 shrink-0 mt-0.5" />Preview is a real FFmpeg/libass render, identical to the final video.</p>
        </div>
      </div>
    </>
  );
}
