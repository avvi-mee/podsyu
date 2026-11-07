"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { CheckCircle2, Copy, KeyRound, Loader2, LogOut, Upload, MonitorPlay } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Empty, PageHeader } from "@/components/common";
import { api, type Account } from "@/lib/api";

type Config = { configured: boolean; client_type?: string; client_id_hint?: string; error?: string; redirect_uri: string };

export default function AccountsPage() {
  const [accounts, setAccounts] = useState<Account[] | null>(null);
  const [cfg, setCfg] = useState<Config | null>(null);
  const [connecting, setConnecting] = useState(false);

  const load = useCallback(() => {
    api<Account[]>("/api/youtube/accounts").then(setAccounts).catch((e) => toast.error(e.message));
    api<Config>("/api/youtube/config").then(setCfg).catch(() => {});
  }, []);
  useEffect(() => {
    load();
    const q = new URLSearchParams(window.location.search);
    if (q.get("connected")) toast.success(`Connected ${q.get("connected")}`);
    if (q.get("error")) toast.error(`YouTube connection failed: ${q.get("error")}`, { duration: 15000 });
    if (q.size) window.history.replaceState(null, "", "/accounts");
  }, [load]);

  const uploadJson = async (f: File) => {
    try {
      setCfg(await api<Config>("/api/youtube/config", { method: "POST", json: { json: await f.text() } }));
      toast.success("OAuth client saved on this computer");
    } catch (e) {
      toast.error((e as Error).message);
    }
  };
  const connect = async () => {
    setConnecting(true);
    try {
      const { url } = await api<{ url: string }>("/api/youtube/oauth/start");
      window.location.href = url;
    } catch (e) {
      toast.error((e as Error).message);
      setConnecting(false);
    }
  };
  const disconnect = async (a: Account) => {
    if (!confirm(`Disconnect ${a.channel_title}? Scheduled uploads for it will fail.`)) return;
    try {
      await api(`/api/youtube/accounts/${a.id}`, { method: "DELETE" });
      toast.success("Disconnected");
      load();
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  return (
    <>
      <PageHeader title="YouTube Accounts" description="Publish through the official YouTube Data API v3 with Google OAuth. Tokens are stored encrypted on this PC.">
        <Button size="lg" disabled={!cfg?.configured || connecting} onClick={connect}>
          {connecting ? <Loader2 className="animate-spin" /> : <MonitorPlay />} Connect YouTube account
        </Button>
      </PageHeader>

      <div className="grid lg:grid-cols-2 gap-4">
        <Card>
          <CardHeader>
            <CardTitle>Connected channels</CardTitle>
            <CardDescription>Each Google sign-in connects the channel you pick on Google&apos;s consent screen.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {accounts?.length === 0 && <Empty icon={MonitorPlay} title="No channels connected">{cfg?.configured ? "Click “Connect YouTube account”." : "Finish the API setup first."}</Empty>}
            {accounts?.map((a) => (
              <div key={a.id} className="flex items-center gap-3 rounded-lg border p-3">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                {a.thumbnail_url ? <img src={a.thumbnail_url} alt="" className="size-10 rounded-full" /> : <MonitorPlay className="size-10 text-red-500" />}
                <div className="min-w-0 flex-1">
                  <div className="font-medium truncate">{a.channel_title}</div>
                  <div className="text-xs text-muted-foreground truncate">{a.channel_id}</div>
                </div>
                <Button size="sm" variant="ghost" onClick={() => disconnect(a)}><LogOut /> Disconnect</Button>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><KeyRound className="size-4 text-primary" /> API setup (one time, free)</CardTitle>
            <CardDescription>
              {cfg?.configured
                ? <span className="text-emerald-400 inline-flex items-center gap-1"><CheckCircle2 className="size-4" /> OAuth client configured ({cfg.client_type}) · {cfg.client_id_hint}</span>
                : cfg?.error ?? "No OAuth client configured yet."}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4 text-sm">
            <ol className="list-decimal pl-5 space-y-1.5 text-muted-foreground">
              <li>Open <a className="text-primary hover:underline" href="https://console.cloud.google.com/projectcreate" target="_blank" rel="noreferrer">Google Cloud Console</a> and create a project (free).</li>
              <li>APIs &amp; Services → Library → enable <b className="text-foreground">YouTube Data API v3</b>.</li>
              <li>OAuth consent screen → External → add yourself under <b className="text-foreground">Test users</b>.</li>
              <li>Credentials → Create credentials → OAuth client ID → <b className="text-foreground">Web application</b>.</li>
              <li>Add this <b className="text-foreground">Authorized redirect URI</b>:</li>
            </ol>
            <div className="flex items-center gap-2 rounded-lg bg-muted p-2 font-mono text-xs">
              <span className="truncate flex-1">{cfg?.redirect_uri}</span>
              <Button size="icon-xs" variant="ghost" aria-label="Copy redirect URI" onClick={() => { navigator.clipboard.writeText(cfg?.redirect_uri ?? ""); toast.success("Copied"); }}><Copy /></Button>
            </div>
            <ol start={6} className="list-decimal pl-5 space-y-1.5 text-muted-foreground">
              <li>Download the client JSON and load it here. It stays in <code>data/secrets</code> and never reaches the browser.</li>
            </ol>
            <label className="inline-flex">
              <input type="file" accept=".json,application/json" className="sr-only" onChange={(e) => e.target.files?.[0] && uploadJson(e.target.files[0])} />
              <span className="inline-flex items-center gap-2 rounded-lg border px-3 h-8 cursor-pointer hover:bg-muted"><Upload className="size-4" /> {cfg?.configured ? "Replace client JSON" : "Load client JSON"}</span>
            </label>
            <p className="text-xs text-muted-foreground">
              While the consent screen is in <b>Testing</b>, Google expires the connection after 7 days (just reconnect), and uploads from unverified projects may be locked to private. See README → “Google OAuth setup”.
            </p>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
