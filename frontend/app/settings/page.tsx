"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Cpu, HardDrive, Loader2, RefreshCw, Save, Trash2 } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { PageHeader, ProgressBar } from "@/components/common";
import { api, fmtBytes, type Options } from "@/lib/api";

type S = Record<string, string | number | boolean>;
type Status = {
  ffmpeg: boolean; whisper_cuda: boolean; yt_dlp: string | null; face_model: boolean; ollama_model: string;
  gpu: { name: string; vram_total_mb: number; vram_used_mb: number; utilization: number; driver: string } | null;
  ollama: { available: boolean; models: string[]; error?: string }; youtube: { configured: boolean };
  disk: { free_gb: number; total_gb: number };
};
type Storage = { projects: { id: number; title: string; source_bytes: number; project_bytes: number; exports_bytes: number }[]; data_dir: string; output_dir: string };
const TIMEZONES = typeof Intl.supportedValuesOf === "function" ? Intl.supportedValuesOf("timeZone") : ["Asia/Kolkata", "UTC"];

export default function SettingsPage() {
  const [s, setS] = useState<S | null>(null);
  const [saved, setSaved] = useState<S | null>(null);
  const [choices, setChoices] = useState<Record<string, string[]>>({});
  const [status, setStatus] = useState<Status | null>(null);
  const [storage, setStorage] = useState<Storage | null>(null);
  const [meta, setMeta] = useState<Options | null>(null);
  const [busy, setBusy] = useState(false);

  const loadStatus = useCallback(() => {
    api<Status>("/api/system/status").then(setStatus).catch((e) => toast.error(e.message));
    api<Storage>("/api/storage").then(setStorage).catch(() => {});
  }, []);
  useEffect(() => {
    api<{ settings: S; choices: Record<string, string[]> }>("/api/settings").then((r) => { setS(r.settings); setSaved(r.settings); setChoices(r.choices); }).catch((e) => toast.error(e.message));
    api<Options>("/api/meta/options").then(setMeta).catch(() => {});
    loadStatus();
  }, [loadStatus]);

  if (!s) return <div className="grid place-items-center h-64"><Loader2 className="animate-spin text-primary" /></div>;
  const set = (k: string, v: string | number | boolean) => setS({ ...s, [k]: v });
  const changed = Object.fromEntries(Object.entries(s).filter(([k, v]) => saved?.[k] !== v));
  const save = async () => {
    setBusy(true);
    try {
      const r = await api<{ settings: S }>("/api/settings", { method: "PUT", json: changed });
      setS(r.settings);
      setSaved(r.settings);
      toast.success("Settings saved");
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const delSource = async (id: number) => {
    try {
      await api(`/api/projects/${id}/delete-source`, { method: "POST" });
      toast.success("Source deleted");
      loadStatus();
    } catch (e) {
      toast.error((e as Error).message);
    }
  };
  const sel = (k: string, opts: string[], labels?: Record<string, string>) => (
    <NativeSelect className="w-full" value={String(s[k])} onChange={(e) => set(k, e.target.value)}>
      {[...new Set([String(s[k]), ...opts])].map((o) => <NativeSelectOption key={o} value={o}>{labels?.[o] ?? o}</NativeSelectOption>)}
    </NativeSelect>
  );
  const num = (k: string) => <Input type="number" value={Number(s[k])} onChange={(e) => set(k, +e.target.value)} />;

  return (
    <>
      <PageHeader title="Settings" description="Everything runs locally. Changes apply to new jobs.">
        <Button disabled={!Object.keys(changed).length || busy} onClick={save}>{busy ? <Loader2 className="animate-spin" /> : <Save />} Save changes</Button>
      </PageHeader>

      <div className="grid lg:grid-cols-2 gap-4">
        <Card>
          <CardHeader className="flex flex-row items-start justify-between">
            <div><CardTitle className="flex items-center gap-2"><Cpu className="size-4 text-primary" /> System</CardTitle><CardDescription>Hardware and dependency check</CardDescription></div>
            <Button size="icon-sm" variant="ghost" aria-label="Refresh" onClick={() => { setStatus(null); loadStatus(); }}><RefreshCw /></Button>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            {!status ? <Loader2 className="animate-spin text-muted-foreground" /> : (
              <>
                {status.gpu ? (
                  <div className="space-y-1.5">
                    <div className="flex justify-between"><span>{status.gpu.name}</span><span className="text-muted-foreground">driver {status.gpu.driver}</span></div>
                    <ProgressBar value={status.gpu.vram_used_mb / status.gpu.vram_total_mb} />
                    <div className="text-xs text-muted-foreground">VRAM {status.gpu.vram_used_mb} / {status.gpu.vram_total_mb} MB · GPU load {status.gpu.utilization}%</div>
                  </div>
                ) : <p className="text-amber-300">No NVIDIA GPU detected - transcription and encoding will use the CPU.</p>}
                <Check ok={status.whisper_cuda} label="faster-whisper CUDA" bad="CPU fallback (slower)" />
                <Check ok={status.ffmpeg} label="FFmpeg" bad="missing - install FFmpeg" />
                <Check ok={status.ollama.available} label={`Ollama (${status.ollama.models.length} models)`} bad={status.ollama.error ? "not running - start Ollama" : "unavailable"} />
                <Check ok={status.ollama.models.includes(status.ollama_model)} label={`Model ${status.ollama_model}`} bad={`not installed - run: ollama pull ${status.ollama_model}`} />
                <Check ok={!!status.yt_dlp} label={`yt-dlp ${status.yt_dlp ?? ""}`} bad="missing" />
                <Check ok={status.face_model} label="Face detector (YuNet)" bad="downloads on first render" />
                <Check ok={status.youtube.configured} label="YouTube OAuth client" bad="not configured (YouTube Accounts page)" />
                <div className="text-xs text-muted-foreground">Disk: {status.disk.free_gb} GB free of {status.disk.total_gb} GB</div>
              </>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>AI models</CardTitle><CardDescription>Smaller models are faster and fit 6 GB VRAM comfortably.</CardDescription></CardHeader>
          <CardContent className="grid grid-cols-2 gap-3">
            <F label="Whisper model">{sel("whisper_model", choices.whisper_model ?? [])}</F>
            <F label="Transcription device">{sel("whisper_device", choices.whisper_device ?? [], { auto: "Auto (GPU if available)", cuda: "GPU (CUDA)", cpu: "CPU" })}</F>
            <F label="Language">{sel("transcription_language", ["auto", "en", "hi", "es", "fr", "de", "pt", "ar", "ja", "ko", "zh"])}</F>
            <F label="Video encoder">{sel("encoder", choices.encoder ?? [], { auto: "Auto (NVENC → CPU)", gpu: "GPU (NVENC)", cpu: "CPU (x264)" })}</F>
            <F label="Ollama model">{sel("ollama_model", status?.ollama.models ?? [])}</F>
            <F label="Ollama context (tokens)">{num("ollama_num_ctx")}</F>
            <div className="col-span-2"><F label="Ollama URL"><Input value={String(s.ollama_url)} onChange={(e) => set("ollama_url", e.target.value)} /></F></div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Defaults</CardTitle></CardHeader>
          <CardContent className="grid grid-cols-3 gap-3">
            <F label="Min duration (s)">{num("min_duration")}</F>
            <F label="Max duration (s)">{num("max_duration")}</F>
            <F label="Shorts per video">{num("num_shorts")}</F>
            <div className="col-span-3 grid grid-cols-2 gap-3">
              <F label="Caption preset">{sel("default_caption_preset", Object.keys(meta?.presets ?? {}), Object.fromEntries(Object.entries(meta?.presets ?? {}).map(([k, v]) => [k, v.name ?? k])))}</F>
              <F label="Output resolution">{sel("output_resolution", choices.output_resolution ?? [])}</F>
              <F label="Publishing timezone">{sel("timezone", TIMEZONES)}</F>
              <F label="Default visibility">{sel("default_privacy", choices.default_privacy ?? [])}</F>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Files &amp; YouTube</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <F label="Output directory (finished MP4s)"><Input value={String(s.output_dir)} onChange={(e) => set("output_dir", e.target.value)} /></F>
            <F label="YouTube OAuth redirect URI (must match Google Cloud)"><Input value={String(s.youtube_redirect_uri)} onChange={(e) => set("youtube_redirect_uri", e.target.value)} /></F>
            <label className="flex items-center justify-between gap-3 text-sm">
              <span>Auto-delete source video by default<span className="block text-xs text-muted-foreground">Default for new projects (each project can override it). The video is deleted only after all its shorts render successfully.</span></span>
              <Switch checked={Boolean(s.auto_cleanup_source)} onCheckedChange={(v) => set("auto_cleanup_source", v)} />
            </label>
          </CardContent>
        </Card>

        <ApiKeysCard />
        <Card className="lg:col-span-2">
          <CardHeader><CardTitle className="flex items-center gap-2"><HardDrive className="size-4 text-primary" /> Storage</CardTitle><CardDescription>{storage?.data_dir}</CardDescription></CardHeader>
          <CardContent>
            <div className="divide-y text-sm">
              {storage?.projects.length === 0 && <p className="text-muted-foreground">No projects.</p>}
              {storage?.projects.map((p) => (
                <div key={p.id} className="flex items-center gap-3 py-2">
                  <span className="flex-1 truncate">{p.title}</span>
                  <span className="text-xs text-muted-foreground tabular-nums w-28 text-right">source {fmtBytes(p.source_bytes)}</span>
                  <span className="text-xs text-muted-foreground tabular-nums w-28 text-right">shorts {fmtBytes(p.exports_bytes)}</span>
                  <Button size="xs" variant="ghost" disabled={!p.source_bytes} onClick={() => delSource(p.id)}><Trash2 /> Delete source</Button>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </>
  );
}

function ApiKeysCard() {
  const [has, setHas] = useState<Record<string, boolean>>({});
  const [form, setForm] = useState({ reddit_client_id: "", reddit_client_secret: "", pexels_api_key: "" });
  useEffect(() => {
    api<Record<string, boolean>>("/api/keys").then(setHas).catch(() => {});
  }, []);
  const save = (json: Record<string, string>) =>
    api<Record<string, boolean>>("/api/keys", { method: "PUT", json })
      .then((r) => { setHas(r); setForm({ reddit_client_id: "", reddit_client_secret: "", pexels_api_key: "" }); toast.success("Saved (encrypted on this PC)"); })
      .catch((e) => toast.error(e.message));
  const field = (k: keyof typeof form, label: string, type = "text") => (
    <F label={`${label} ${has[k] ? "· saved ✓" : "· not set"}`}>
      <Input type={type} value={form[k]} placeholder={has[k] ? "•••••• (leave empty to keep)" : ""} onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
    </F>
  );
  const filled = Object.fromEntries(Object.entries(form).filter(([, v]) => v.trim()));
  return (
    <Card className="lg:col-span-2">
      <CardHeader><CardTitle>Content source API keys</CardTitle><CardDescription>Free keys, stored encrypted on this PC and never shown in the browser.</CardDescription></CardHeader>
      <CardContent className="grid md:grid-cols-3 gap-3">
        {field("reddit_client_id", "Reddit client ID")}
        {field("reddit_client_secret", "Reddit client secret", "password")}
        {field("pexels_api_key", "Pexels API key", "password")}
        <p className="md:col-span-3 text-xs text-muted-foreground">
          Reddit: reddit.com/prefs/apps → create app → type &quot;script&quot; (used only to discover stories via the official API).
          Pexels: pexels.com/api → free key (licensed stock footage for the Media Library).
        </p>
        <div className="md:col-span-3 flex gap-2">
          <Button disabled={!Object.keys(filled).length} onClick={() => save(filled)}><Save /> Save keys</Button>
          {(has.reddit_client_id || has.pexels_api_key) && (
            <Button variant="ghost" onClick={() => confirm("Remove all saved API keys?") && save({ reddit_client_id: "", reddit_client_secret: "", pexels_api_key: "" })}><Trash2 /> Remove keys</Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function F({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="space-y-1.5 min-w-0"><Label className="text-xs text-muted-foreground">{label}</Label>{children}</div>;
}

function Check({ ok, label, bad }: { ok: boolean; label: string; bad: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="flex items-center gap-2"><span className={`size-2 rounded-full ${ok ? "bg-emerald-400" : "bg-amber-400"}`} />{label}</span>
      <span className={`text-xs ${ok ? "text-emerald-400" : "text-amber-300"}`}>{ok ? "OK" : bad}</span>
    </div>
  );
}
