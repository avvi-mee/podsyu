export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export type Job = {
  id: number; type: string; project_id: number | null; short_id: number | null; status: string; stage: string;
  progress: number; message: string; error: string | null; label?: string; created_at: string; finished_at: string | null;
};
export type Project = {
  id: number; title: string; source_type: "youtube" | "local" | "story" | "cutting"; source_url: string | null; channel: string | null;
  thumbnail_url: string | null; duration: number | null; width: number | null; height: number | null; status: string;
  error: string | null; options: Record<string, unknown>; caption_style: CaptionStyle | null; language: string | null;
  source_deleted: boolean; created_at: string; shorts_total?: number; shorts_ready?: number;
  music: string | null; music_volume: number | null; engine: string | null;
};
export type Publication = {
  id: number; short_id: number; account_id: number; title: string; description: string; tags: string[];
  privacy: string; mode: "now" | "youtube" | "local"; publish_at: string | null; status: string; progress: number;
  youtube_video_id: string | null; message: string | null; error: string | null; created_at: string; updated_at: string;
  short_title?: string; project_id?: number; channel_title?: string;
};
export type Short = {
  id: number; project_id: number; rank: number; start: number; end: number; transcript: string; hook: string;
  title: string; description: string; hashtags: string; category: string; reason: string; score: number;
  status: string; review: "none" | "approved" | "rejected"; video_path: string | null; caption_style: CaptionStyle | null;
  crop_mode: "auto" | "manual"; crop_x: number; framing: string | null; error: string | null; updated_at: string;
  music: string | null; music_volume: number | null; details: ShortDetails | null; engine?: string;
  project_title?: string; source_available?: boolean; publications?: Publication[]; busy?: boolean; youtube_id?: string | null;
};
export type ProjectDetail = Project & {
  source_available: boolean; transcript_available: boolean; shorts: Short[]; jobs: Job[]; publications: Publication[];
};
export type CaptionStyle = {
  preset?: string; name?: string; font: string; font_size: number; bold: boolean; italic: boolean; uppercase: boolean;
  text_color: string; highlight_color: string; highlight: boolean; outline_color: string; outline_width: number;
  shadow: number; position: string; words_per_line: number; animation: string; background: string;
  background_color: string; letter_spacing: number;
};
export type ShortDetails = {
  scene?: string; analysis?: string; scores?: Record<string, number | null>; signals?: Record<string, number | null>;
  background?: string; story_id?: number; source?: string; url?: string | null;
};
export type MusicTrack = {
  id: number; filename: string; title: string; credit: string; duration: number; category: string | null;
  license: string | null; source_url: string | null; favourite: boolean | null; parent_id: number | null; clip_start: number | null;
};
export type BackgroundMedia = {
  id: number; filename: string; title: string; category: string; duration: number; width: number; height: number;
  source: string; source_url: string | null; creator: string | null; license: string | null; attribution: string | null; favourite: boolean;
};
export type Story = {
  id: number; source_type: "reddit" | "user" | "ai_original" | "licensed"; title: string; body: string; category: string;
  permission: string; attribution: string | null; subreddit: string | null; author: string | null; url: string | null;
  score: number | null; num_comments: number | null; posted_at: string | null; nsfw: boolean; script: string | null;
  status: string; created_at: string; suitability: string; words: number;
};
export type Voice = { profile: string; pitch: number; speed: number; volume: number; emotion: string; pause: number; pronunciation: string };
export const ENGINE_LABEL: Record<string, string> = { podcast: "Podcast", creator: "Famous Creator", asmr: "ASMR Story", cutting: "ASMR Cutting" };
export const MUSIC_LEVELS = [
  { v: 0.06, label: "Very low" }, { v: 0.1, label: "Low (recommended)" }, { v: 0.16, label: "Medium" },
];
export type Account = { id: number; channel_id: string; channel_title: string; thumbnail_url: string | null };
export type Options = {
  categories: string[]; strategies: Record<string, string>; presets: Record<string, CaptionStyle>; fonts: string[];
  positions: string[]; animations: string[];
};

export class ApiError extends Error {}

export async function api<T = unknown>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const { json, ...rest } = init ?? {};
  let res: Response;
  try {
    res = await fetch(API + path, {
      ...rest,
      headers: json !== undefined ? { "Content-Type": "application/json", ...rest.headers } : rest.headers,
      body: json !== undefined ? JSON.stringify(json) : rest.body,
      cache: "no-store",
    });
  } catch {
    throw new ApiError("Backend is not reachable at " + API + ". Is it running? (start.bat)");
  }
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {}
    throw new ApiError(msg || `Request failed (${res.status})`);
  }
  const type = res.headers.get("content-type") ?? "";
  return (type.includes("json") ? res.json() : res.blob()) as Promise<T>;
}

export const fmtTime = (s: number | null | undefined) => {
  if (s == null) return "-";
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = Math.floor(s % 60);
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}` : `${m}:${String(sec).padStart(2, "0")}`;
};

export const fmtDate = (iso: string | null | undefined, tz?: string, withTime = true) =>
  iso
    ? new Intl.DateTimeFormat("en-IN", {
        timeZone: tz, day: "numeric", month: "short", year: "numeric",
        ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
      }).format(new Date(iso))
    : "-";

export const fmtBytes = (b: number) =>
  b > 2 ** 30 ? `${(b / 2 ** 30).toFixed(2)} GB` : b > 2 ** 20 ? `${(b / 2 ** 20).toFixed(1)} MB` : `${Math.round(b / 1024)} KB`;
