"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { Loader2, Send } from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { api, type Account, type Short } from "@/lib/api";
import { cn } from "@/lib/utils";

const WHEN = [
  { v: "now", label: "Publish now", hint: "Uploads immediately with the visibility you choose." },
  { v: "youtube", label: "Schedule on YouTube", hint: "Uploads now as private; YouTube makes it public at the chosen time. Your PC can be off." },
  { v: "local", label: "Schedule upload (this app)", hint: "This app uploads at the chosen time. Your PC and the app must be running then." },
] as const;

export function PublishDialog({ short, open, onOpenChange, onDone }: { short: Short; open: boolean; onOpenChange: (o: boolean) => void; onDone?: () => void }) {
  const [accounts, setAccounts] = useState<Account[] | null>(null);
  const [tz, setTz] = useState("Asia/Kolkata");
  const [form, setForm] = useState({
    account_id: 0, title: short.title, description: short.description, hashtags: short.hashtags,
    privacy: "public", mode: "now" as (typeof WHEN)[number]["v"], publish_at: "", made_for_kids: false,
  });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<Account[]>("/api/youtube/accounts").then((a) => {
      setAccounts(a);
      if (a[0]) setForm((f) => ({ ...f, account_id: f.account_id || a[0].id }));
    }).catch((e) => toast.error(e.message));
    api<{ settings: { timezone: string; default_privacy: string } }>("/api/settings").then(({ settings }) => {
      setTz(settings.timezone);
      setForm((f) => ({ ...f, privacy: settings.default_privacy }));
    }).catch(() => {});
  }, []); // mounted only while open, so this runs once per opening

  const submit = async () => {
    setBusy(true);
    try {
      await api("/api/publications", {
        method: "POST",
        json: { ...form, short_id: short.id, timezone: tz, publish_at: form.mode === "now" ? undefined : form.publish_at },
      });
      toast.success(form.mode === "now" ? "Upload queued - track progress in the calendar" : "Scheduled");
      onOpenChange(false);
      onDone?.();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Publish to YouTube</DialogTitle>
          <DialogDescription>Uses the official YouTube Data API with your connected account.</DialogDescription>
        </DialogHeader>
        {accounts?.length === 0 ? (
          <p className="text-sm">No YouTube account connected. <Link className="text-primary underline" href="/accounts">Connect one first</Link>.</p>
        ) : (
          <div className="space-y-3">
            <Field label="Channel">
              <NativeSelect className="w-full" value={form.account_id} onChange={(e) => setForm({ ...form, account_id: +e.target.value })}>
                {accounts?.map((a) => <NativeSelectOption key={a.id} value={a.id}>{a.channel_title}</NativeSelectOption>)}
              </NativeSelect>
            </Field>
            <Field label={`Title (${form.title.length}/100)`}>
              <Input value={form.title} maxLength={100} onChange={(e) => setForm({ ...form, title: e.target.value })} />
            </Field>
            <Field label="Description">
              <Textarea rows={3} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
            </Field>
            <Field label="Hashtags (added to the description and as tags)">
              <Input value={form.hashtags} onChange={(e) => setForm({ ...form, hashtags: e.target.value })} />
            </Field>
            <Field label="When">
              <div className="grid gap-2">
                {WHEN.map((w) => (
                  <button key={w.v} type="button" onClick={() => setForm({ ...form, mode: w.v })}
                    className={cn("text-left rounded-lg border p-2.5 text-sm transition-colors", form.mode === w.v ? "border-primary bg-primary/10" : "hover:bg-muted/50")}>
                    <div className="font-medium">{w.label}</div>
                    <div className="text-xs text-muted-foreground">{w.hint}</div>
                  </button>
                ))}
              </div>
            </Field>
            {form.mode !== "now" && (
              <Field label={`Publish time (${tz})`}>
                <Input type="datetime-local" value={form.publish_at} onChange={(e) => setForm({ ...form, publish_at: e.target.value })} />
              </Field>
            )}
            {form.mode !== "youtube" ? (
              <Field label="Visibility">
                <NativeSelect className="w-full" value={form.privacy} onChange={(e) => setForm({ ...form, privacy: e.target.value })}>
                  <NativeSelectOption value="public">Public</NativeSelectOption>
                  <NativeSelectOption value="unlisted">Unlisted</NativeSelectOption>
                  <NativeSelectOption value="private">Private</NativeSelectOption>
                </NativeSelect>
              </Field>
            ) : (
              <p className="text-xs text-muted-foreground">Visibility: private until the scheduled time, then public.</p>
            )}
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <Checkbox checked={form.made_for_kids} onCheckedChange={(v) => setForm({ ...form, made_for_kids: v === true })} />
              This video is made for kids (COPPA)
            </label>
            <Button className="w-full" disabled={busy || !form.account_id || (form.mode !== "now" && !form.publish_at)} onClick={submit}>
              {busy ? <Loader2 className="animate-spin" /> : <Send />} {form.mode === "now" ? "Upload now" : "Schedule"}
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      {children}
    </div>
  );
}
