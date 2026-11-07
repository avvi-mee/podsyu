"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import {
  BookOpen, Check, Dices, Film, Info, Loader2, Moon, PenLine, Play, Search, ShieldAlert, Sparkles, Trash2, Upload, Wand2, X,
} from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Slider } from "@/components/ui/slider";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Empty, JobRow, PageHeader } from "@/components/common";
import { BackgroundLibrary } from "@/components/background-library";
import { ShortCard } from "@/components/short-card";
import {
  api, API, MUSIC_LEVELS, type BackgroundMedia, type MusicTrack, type Options, type ProjectDetail, type Short, type Story, type Voice,
} from "@/lib/api";
import { useLive, useLiveRefresh } from "@/lib/live";
import { cn } from "@/lib/utils";

type Status = { tts: boolean; reddit: boolean; categories: Record<string, string>; profiles: string[]; emotions: string[]; default_voice: Voice; seconds: number[] };
type StoryProject = ProjectDetail & { short: Short | null };
const SOURCE_LABEL: Record<string, string> = { reddit: "Reddit", user: "My story", ai_original: "AI original (fiction)", licensed: "Licensed" };
const PERMISSION: Record<string, { label: string; tone: string }> = {
  not_required: { label: "OK to use", tone: "text-emerald-400" }, granted: { label: "Permission granted", tone: "text-emerald-400" },
  needs_permission: { label: "Needs author's permission", tone: "text-amber-300" }, unknown: { label: "Permission unknown", tone: "text-amber-300" },
};
const nice = (k: string) => k.replace("_", " ").replace(/^\w/, (c) => c.toUpperCase());

export default function AsmrPage() {
  const [status, setStatus] = useState<Status | null>(null);
  const [category, setCategory] = useState("dark");
  const [stories, setStories] = useState<Story[] | null>(null);
  const [current, setCurrent] = useState<Story | null>(null);
  const [busy, setBusy] = useState<string>("");
  const [discoverOpen, setDiscoverOpen] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [customOpen, setCustomOpen] = useState(false);
  const [projects, setProjects] = useState<StoryProject[]>([]);
  const [meta, setMeta] = useState<Options | null>(null);
  const [bg, setBg] = useState("auto"); // background footage for the next short ("auto" = match the mood)
  const [media, setMedia] = useState<BackgroundMedia[]>([]);

  const loadStories = useCallback(() => api<Story[]>("/api/asmr/stories").then(setStories).catch((e) => toast.error(e.message)), []);
  const loadProjects = useCallback(() => api<StoryProject[]>("/api/asmr/projects").then(setProjects).catch(() => {}), []);
  useEffect(() => {
    api<Status>("/api/asmr/status").then(setStatus).catch((e) => toast.error(e.message));
    api<Options>("/api/meta/options").then(setMeta).catch(() => {});
    loadStories();
    loadProjects();
  }, [loadStories, loadProjects]);
  useLiveRefresh(() => { loadProjects(); loadStories(); }, (j) => j.type === "asmr" || j.type === "render" || j.type === "metadata");

  const run = async <T,>(label: string, fn: () => Promise<T>, ok: string) => {
    setBusy(label);
    try {
      const r = await fn();
      toast.success(ok);
      return r;
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy("");
    }
  };
  const randomStory = () =>
    run("random", () => api<Story>("/api/asmr/stories/generate", { method: "POST", json: { category } }), "Original story written").then((st) => {
      if (st) { loadStories(); setCurrent(st); }
    });

  const visible = (stories ?? []).filter((s) => s.status !== "rejected");

  return (
    <>
      <PageHeader title="ASMR STORIES FACTORY" description="Stories that keep people watching." />
      {status && !status.tts && (
        <div className="mb-4 flex gap-2 rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm"><ShieldAlert className="size-4 mt-0.5 text-red-300" />
          Local voice model not installed. Run scripts\setup.bat (downloads the Kokoro voice model, ~350 MB).</div>
      )}
      <Card className="mb-4">
        <CardContent className="flex flex-wrap items-center gap-2 pt-1">
          <NativeSelect value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Story category">
            {status && Object.keys(status.categories).map((c) => <NativeSelectOption key={c} value={c}>{nice(c)}</NativeSelectOption>)}
          </NativeSelect>
          <Button onClick={() => setDiscoverOpen(true)}><Search /> Find Stories</Button>
          <Button variant="outline" disabled={!!busy} onClick={randomStory}>{busy === "random" ? <Loader2 className="animate-spin" /> : <Dices />} Generate Random Story</Button>
          <Button variant="outline" onClick={() => setUploadOpen(true)}><Upload /> Upload My Own Story</Button>
          <Button variant="outline" onClick={() => setCustomOpen(true)}><PenLine /> Create Custom Story</Button>
          <Button variant="outline" render={<a href="#backgrounds" />} nativeButton={false}><Film /> My background videos ({media.length})</Button>
          <span className="ml-auto text-xs text-muted-foreground">{status?.categories[category]}</span>
        </CardContent>
      </Card>

      <div className="grid xl:grid-cols-[380px_1fr] gap-4">
        <Card className="self-start">
          <CardHeader><CardTitle className="flex items-center gap-2"><BookOpen className="size-4 text-primary" /> Stories</CardTitle><CardDescription>Pick one to turn into a short.</CardDescription></CardHeader>
          <CardContent className="space-y-2 max-h-[75vh] overflow-y-auto">
            {visible.length === 0 && <Empty icon={Moon} title="No stories yet">Generate a random story, write your own, or find stories.</Empty>}
            {visible.map((s) => (
              <button key={s.id} onClick={() => setCurrent(s)} className={cn("w-full text-left rounded-lg border p-3 space-y-1.5 hover:bg-muted/40", current?.id === s.id && "border-primary bg-primary/5")}>
                <div className="font-medium text-sm leading-snug line-clamp-2">{s.title}</div>
                <div className="flex flex-wrap gap-1.5 text-[11px]">
                  <Badge variant="secondary" className="border-0">{SOURCE_LABEL[s.source_type]}</Badge>
                  <Badge variant="outline">{nice(s.category)}</Badge>
                  <span className={PERMISSION[s.permission]?.tone}>{PERMISSION[s.permission]?.label}</span>
                  {s.suitability !== "ok" && <span className="text-red-300">· {s.suitability}</span>}
                </div>
                <p className="text-xs text-muted-foreground line-clamp-2">{s.body}</p>
                <p className="text-[11px] text-muted-foreground">
                  {s.words} words · ~{Math.round(s.words / 2.6)}s read{s.score != null && ` · ▲ ${s.score} · ${s.num_comments} comments · r/${s.subreddit}`}{s.status === "used" && " · used"}
                </p>
              </button>
            ))}
          </CardContent>
        </Card>
        {current ? (
          <Studio key={current.id} story={current} status={status} meta={meta} bg={bg} setBg={setBg} media={media}
            onChanged={(st) => { loadStories(); if (st) setCurrent(st); else setCurrent(null); }} onGenerated={loadProjects} />
        ) : (
          <Card><CardContent><Empty icon={Sparkles} title="Select a story">Then rewrite it for Shorts, pick a voice and click Generate Short.</Empty></CardContent></Card>
        )}
      </div>

      <section id="backgrounds" className="mt-8 scroll-mt-4">
        <h2 className="text-lg font-semibold mb-1">My background videos</h2>
        <p className="text-sm text-muted-foreground mb-3">
          Upload your own ASMR footage (gameplay, parkour, slime, cleaning, cooking...), generate original loops or import licensed stock.
          Click <b>Use for this story</b> to pick one, or leave it on Auto to match each story&apos;s mood.
        </p>
        <BackgroundLibrary onItems={setMedia} pickedId={bg === "auto" ? null : Number(bg)} onPick={(id) => { setBg(id ? String(id) : "auto"); toast.success(id ? "Background selected for the next short" : "Background back to Auto"); }} />
      </section>

      <h2 className="text-lg font-semibold mt-8 mb-3">Story shorts</h2>
      {projects.length === 0 && <p className="text-sm text-muted-foreground">Generated story shorts appear here, ready to publish.</p>}
      <div className="space-y-4">
        {projects.map((p) => p.short && (
          <div key={p.id}>
            <ProjectProgress projectId={p.id} />
            <ShortCard short={p.short} meta={meta} projectStyle={p.caption_style} engine="asmr" onChanged={loadProjects} />
          </div>
        ))}
      </div>

      <DiscoverDialog open={discoverOpen} onOpenChange={setDiscoverOpen} category={category} reddit={!!status?.reddit} onFound={loadStories} />
      <UploadDialog open={uploadOpen} onOpenChange={setUploadOpen} category={category} onAdded={(st) => { loadStories(); setCurrent(st); }} />
      <CustomDialog open={customOpen} onOpenChange={setCustomOpen} category={category} onAdded={(st) => { loadStories(); setCurrent(st); }} />
    </>
  );
}

function ProjectProgress({ projectId }: { projectId: number }) {
  const { jobs } = useLive();
  const job = jobs.find((j) => j.project_id === projectId && j.type === "asmr" && (j.status === "running" || j.status === "queued" || j.status === "failed"));
  return job ? <div className="mb-2"><JobRow job={job} showLabel={false} /></div> : null;
}

function Studio({ story, status, meta, bg, setBg, media, onChanged, onGenerated }: {
  story: Story; status: Status | null; meta: Options | null; bg: string; setBg: (v: string) => void; media: BackgroundMedia[];
  onChanged: (s: Story | null) => void; onGenerated: () => void;
}) {
  const [seconds, setSeconds] = useState(45);
  const [script, setScript] = useState(story.script ?? "");
  const [voice, setVoice] = useState<Voice>(status?.default_voice ?? { profile: "expressive", pitch: 0, speed: 1, volume: 0, emotion: "neutral", pause: 0.35, pronunciation: "" });
  const [preview, setPreview] = useState<string>("");
  const [music, setMusic] = useState("auto");
  const [level, setLevel] = useState(0.1);
  const [preset, setPreset] = useState("hormozi");
  const [tracks, setTracks] = useState<MusicTrack[]>([]);
  const [busy, setBusy] = useState("");
  const ok = story.permission === "granted" || story.permission === "not_required";

  useEffect(() => {
    api<MusicTrack[]>("/api/music").then(setTracks).catch(() => {});
  }, []);

  const call = async <T,>(label: string, fn: () => Promise<T>) => {
    setBusy(label);
    try {
      return await fn();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy("");
    }
  };
  const adapt = () => call("adapt", async () => {
    const r = await api<{ script: string; estimated_seconds: number }>(`/api/asmr/stories/${story.id}/adapt`, { method: "POST", json: { seconds } });
    setScript(r.script);
    toast.success(`Script ready (~${r.estimated_seconds}s)`);
  });
  const previewVoice = () => call("voice", async () => {
    const text = (script || story.body).split(/(?<=[.!?])\s+/).slice(0, 3).join(" ");
    const r = await api<{ url: string }>("/api/asmr/voice-preview", { method: "POST", json: { text, voice } });
    setPreview(`${API}${r.url}`);
  });
  const patch = (json: object, msg: string) => call("patch", async () => {
    const st = await api<Story>(`/api/asmr/stories/${story.id}`, { method: "PATCH", json });
    toast.success(msg);
    onChanged(st);
  });
  const inspired = () => call("inspired", async () => {
    const st = await api<Story>("/api/asmr/stories/generate", { method: "POST", json: { category: story.category, inspired_by: story.id } });
    toast.success("New original story written on the same theme");
    onChanged(st);
  });
  const generate = () => call("generate", async () => {
    await api("/api/asmr/generate", {
      method: "POST",
      json: {
        story_id: story.id, seconds, script: script || undefined, voice, background_id: bg === "auto" ? null : Number(bg),
        music, music_volume: level, caption_style: { preset },
      },
    });
    toast.success("Generating your short - progress is shown below");
    onGenerated();
  });
  const num = (v: number | readonly number[]) => (Array.isArray(v) ? v[0] : (v as number));

  return (
    <Card>
      <CardHeader>
        <CardTitle className="leading-snug">{story.title}</CardTitle>
        <CardDescription className="flex flex-wrap gap-2 items-center">
          <span>{SOURCE_LABEL[story.source_type]}</span>
          <span className={PERMISSION[story.permission]?.tone}>{PERMISSION[story.permission]?.label}</span>
          {story.attribution && <span>· {story.attribution}</span>}
          {story.url && <a className="text-primary underline" href={story.url} target="_blank" rel="noreferrer">source</a>}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <details>
          <summary className="cursor-pointer text-sm text-muted-foreground">Read story ({story.words} words)</summary>
          <p className="mt-2 whitespace-pre-line text-sm leading-relaxed max-h-64 overflow-y-auto">{story.body}</p>
        </details>
        {!ok && (
          <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm space-y-2">
            <p className="flex gap-2"><Info className="size-4 mt-0.5 shrink-0 text-amber-300" /> Reddit stories belong to their authors. Get the author&apos;s permission before publishing it as a video, or write a new original story on the same theme.</p>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="outline" onClick={() => confirm("Confirm you have the author's permission to use this story in a video.") && patch({ permission: "granted" }, "Permission recorded")}><Check /> I have the author&apos;s permission</Button>
              <Button size="sm" disabled={!!busy} onClick={inspired}>{busy === "inspired" ? <Loader2 className="animate-spin" /> : <Wand2 />} Write original inspired by this</Button>
            </div>
          </div>
        )}
        <div className="space-y-2">
          <div className="flex flex-wrap items-end gap-2">
            <div className="space-y-1"><Label className="text-xs text-muted-foreground">Target length</Label>
              <NativeSelect value={seconds} onChange={(e) => setSeconds(+e.target.value)}>
                {(status?.seconds ?? [15, 30, 45, 60, 90]).map((s) => <NativeSelectOption key={s} value={s}>{s} seconds</NativeSelectOption>)}
              </NativeSelect></div>
            <Button variant="outline" disabled={!!busy} onClick={adapt}>{busy === "adapt" ? <Loader2 className="animate-spin" /> : <Sparkles />} Rewrite for Shorts</Button>
            <Button variant="ghost" onClick={() => patch({ status: "rejected" }, "Story hidden")}><X /> Reject</Button>
            <Button variant="ghost" onClick={() => confirm("Delete this story?") && api(`/api/asmr/stories/${story.id}`, { method: "DELETE" }).then(() => onChanged(null))}><Trash2 /></Button>
          </div>
          <Textarea rows={6} value={script} placeholder="Click 'Rewrite for Shorts' (or write your own narration). Leave empty and it's written automatically." onChange={(e) => setScript(e.target.value)} />
          <p className="text-xs text-muted-foreground">{script ? `${script.split(/\s+/).length} words · ~${Math.round(script.split(/\s+/).length / 2.6)} s of narration` : "Hook → setup → incident → escalation → twist."}</p>
        </div>

        <div className="grid md:grid-cols-2 gap-5">
          <div className="space-y-3 rounded-lg border p-3">
            <div className="text-sm font-medium">Voice (local, Kokoro TTS)</div>
            <div className="grid grid-cols-2 gap-2">
              <NativeSelect value={voice.profile} onChange={(e) => setVoice({ ...voice, profile: e.target.value })} aria-label="Voice">
                {status?.profiles.map((p) => <NativeSelectOption key={p} value={p}>{p === "expressive" ? "Expressive (default)" : nice(p)}</NativeSelectOption>)}
              </NativeSelect>
              <NativeSelect value={voice.emotion} onChange={(e) => setVoice({ ...voice, emotion: e.target.value })} aria-label="Emotion">
                {status?.emotions.map((p) => <NativeSelectOption key={p} value={p}>{nice(p)}</NativeSelectOption>)}
              </NativeSelect>
            </div>
            <Row label={`Pitch ${voice.pitch > 0 ? "+" : ""}${voice.pitch} st`}><Slider min={-4} max={4} step={0.5} value={[voice.pitch]} onValueChange={(v) => setVoice({ ...voice, pitch: num(v) })} /></Row>
            <Row label={`Speed ${voice.speed.toFixed(2)}×`}><Slider min={0.7} max={1.4} step={0.05} value={[voice.speed]} onValueChange={(v) => setVoice({ ...voice, speed: num(v) })} /></Row>
            <Row label={`Volume ${voice.volume > 0 ? "+" : ""}${voice.volume} dB`}><Slider min={-6} max={6} step={1} value={[voice.volume]} onValueChange={(v) => setVoice({ ...voice, volume: num(v) })} /></Row>
            <Row label={`Pause between sentences ${voice.pause.toFixed(2)} s`}><Slider min={0.1} max={1.2} step={0.05} value={[voice.pause]} onValueChange={(v) => setVoice({ ...voice, pause: num(v) })} /></Row>
            <Textarea rows={2} value={voice.pronunciation} placeholder="Pronunciation fixes, one per line: GIF = jif" onChange={(e) => setVoice({ ...voice, pronunciation: e.target.value })} />
            <Button size="sm" variant="outline" disabled={!!busy || !status?.tts} onClick={previewVoice}>{busy === "voice" ? <Loader2 className="animate-spin" /> : <Play />} Preview voice</Button>
            {preview && <audio key={preview} src={preview} controls autoPlay className="w-full h-9" />}
          </div>
          <div className="space-y-3 rounded-lg border p-3">
            <div className="text-sm font-medium">Look &amp; sound</div>
            <Row label="Background video">
              <NativeSelect className="w-full" value={bg} onChange={(e) => setBg(e.target.value)}>
                <NativeSelectOption value="auto">Auto - match the story&apos;s mood</NativeSelectOption>
                {media.map((m) => <NativeSelectOption key={m.id} value={m.id}>{m.favourite ? "★ " : ""}{m.title} ({m.category})</NativeSelectOption>)}
              </NativeSelect>
            </Row>
            {media.length === 0 && <p className="text-xs text-amber-300">No background videos yet - add some under <a className="underline" href="#backgrounds">My background videos</a> below.</p>}
            <Row label="Background music">
              <div className="flex gap-2">
                <NativeSelect className="flex-1" value={music} onChange={(e) => setMusic(e.target.value)}>
                  <NativeSelectOption value="auto">Auto - match the story&apos;s mood</NativeSelectOption>
                  <NativeSelectOption value="none">No music</NativeSelectOption>
                  {tracks.map((t) => <NativeSelectOption key={t.id} value={String(t.id)}>{t.favourite ? "★ " : ""}{t.title}{t.category ? ` (${t.category})` : ""}</NativeSelectOption>)}
                </NativeSelect>
                <NativeSelect value={level} disabled={music === "none"} onChange={(e) => setLevel(+e.target.value)} aria-label="Music volume">
                  {MUSIC_LEVELS.map((l) => <NativeSelectOption key={l.v} value={l.v}>{l.label}</NativeSelectOption>)}
                </NativeSelect>
              </div>
            </Row>
            <Row label="Captions">
              <NativeSelect className="w-full" value={preset} onChange={(e) => setPreset(e.target.value)}>
                {meta && Object.entries(meta.presets).map(([k, p]) => <NativeSelectOption key={k} value={k}>{p.name}</NativeSelectOption>)}
              </NativeSelect>
            </Row>
            <p className="text-xs text-muted-foreground">Voice stays clear: music is quiet, ducks under the narration and fades in/out. Captions are word-synced to the voice.</p>
          </div>
        </div>
        <Button size="lg" className="w-full h-12 text-base" disabled={!ok || !!busy || !status?.tts} onClick={generate}>
          {busy === "generate" ? <Loader2 className="animate-spin" /> : <Sparkles />} Generate Short
        </Button>
      </CardContent>
    </Card>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="space-y-1.5"><Label className="text-xs text-muted-foreground">{label}</Label>{children}</div>;
}

function DiscoverDialog({ open, onOpenChange, category, reddit, onFound }: { open: boolean; onOpenChange: (o: boolean) => void; category: string; reddit: boolean; onFound: () => void }) {
  const [f, setF] = useState({ subreddit: "", keyword: "", sort: "top", period: "week", min_score: 100, min_comments: 10 });
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try {
      const r = await api<{ found: number; added: number }>("/api/asmr/discover", { method: "POST", json: { ...f, category } });
      toast.success(`Found ${r.found} text stories, ${r.added} new`);
      onFound();
      onOpenChange(false);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Find stories on Reddit</DialogTitle>
          <DialogDescription>Uses Reddit&apos;s official API. Stories stay marked &quot;needs permission&quot; until you confirm you have it.</DialogDescription>
        </DialogHeader>
        {!reddit ? (
          <p className="text-sm">Reddit isn&apos;t connected. Create a free &quot;script&quot; app at reddit.com/prefs/apps and add its client ID and secret in <Link className="text-primary underline" href="/settings">Settings</Link>. Meanwhile, use Generate Random Story or Create Custom Story.</p>
        ) : (
          <div className="grid grid-cols-2 gap-3">
            <Row label="Subreddit (blank = category default)"><Input value={f.subreddit} placeholder="tifu" onChange={(e) => setF({ ...f, subreddit: e.target.value })} /></Row>
            <Row label="Keyword"><Input value={f.keyword} onChange={(e) => setF({ ...f, keyword: e.target.value })} /></Row>
            <Row label="Sort"><NativeSelect className="w-full" value={f.sort} onChange={(e) => setF({ ...f, sort: e.target.value })}>
              {["top", "hot", "new"].map((s) => <NativeSelectOption key={s} value={s}>{s}</NativeSelectOption>)}</NativeSelect></Row>
            <Row label="Posted within"><NativeSelect className="w-full" value={f.period} onChange={(e) => setF({ ...f, period: e.target.value })}>
              {["day", "week", "month", "year", "all"].map((s) => <NativeSelectOption key={s} value={s}>{s}</NativeSelectOption>)}</NativeSelect></Row>
            <Row label="Min score"><Input type="number" value={f.min_score} onChange={(e) => setF({ ...f, min_score: +e.target.value })} /></Row>
            <Row label="Min comments"><Input type="number" value={f.min_comments} onChange={(e) => setF({ ...f, min_comments: +e.target.value })} /></Row>
            <Button className="col-span-2" disabled={busy} onClick={go}>{busy ? <Loader2 className="animate-spin" /> : <Search />} Search</Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function UploadDialog({ open, onOpenChange, category, onAdded }: { open: boolean; onOpenChange: (o: boolean) => void; category: string; onAdded: (s: Story) => void }) {
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const save = () =>
    api<Story>("/api/asmr/stories", { method: "POST", json: { title, body, category, source_type: "user" } })
      .then((st) => { toast.success("Story added"); onAdded(st); onOpenChange(false); setTitle(""); setBody(""); })
      .catch((e) => toast.error(e.message));
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader><DialogTitle>Upload my own story</DialogTitle><DialogDescription>Paste it, or load a .txt file.</DialogDescription></DialogHeader>
        <Input value={title} placeholder="Title" onChange={(e) => setTitle(e.target.value)} />
        <Textarea rows={10} value={body} placeholder="Your story..." onChange={(e) => setBody(e.target.value)} />
        <div className="flex gap-2">
          <label>
            <input type="file" accept=".txt,text/plain" className="sr-only" onChange={async (e) => { const f = e.target.files?.[0]; if (f) { setBody(await f.text()); if (!title) setTitle(f.name.replace(/\.txt$/, "")); } }} />
            <span className="inline-flex h-8 items-center gap-2 rounded-lg border px-2.5 text-sm cursor-pointer"><Upload className="size-4" /> .txt file</span>
          </label>
          <Button className="ml-auto" disabled={!title.trim() || body.split(/\s+/).length < 30} onClick={save}>Add story</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function CustomDialog({ open, onOpenChange, category, onAdded }: { open: boolean; onOpenChange: (o: boolean) => void; category: string; onAdded: (s: Story) => void }) {
  const [idea, setIdea] = useState("");
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try {
      const st = await api<Story>("/api/asmr/stories/generate", { method: "POST", json: { category, idea } });
      toast.success("Original story written");
      onAdded(st);
      onOpenChange(false);
      setIdea("");
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader><DialogTitle>Create custom story</DialogTitle><DialogDescription>Describe the idea; the local AI writes an original story ({nice(category)}).</DialogDescription></DialogHeader>
        <Textarea rows={5} value={idea} placeholder="e.g. a pizza delivery to a house that doesn't exist on any map" onChange={(e) => setIdea(e.target.value)} />
        <Button disabled={busy || !idea.trim()} onClick={go}>{busy ? <Loader2 className="animate-spin" /> : <Wand2 />} Write story</Button>
      </DialogContent>
    </Dialog>
  );
}
