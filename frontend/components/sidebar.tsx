"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  CalendarDays, Captions, Clapperboard, FolderOpen, Gamepad2, LayoutDashboard, Library, Mic, MonitorPlay, Moon, Rocket, Settings, Slice,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useLive } from "@/lib/live";

export const NAV = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/autopilot", label: "Autopilot", icon: Rocket },
  { href: "/create", label: "Podcast Clipper", icon: Mic },
  { href: "/creators", label: "Famous Creators Clipper", icon: Gamepad2 },
  { href: "/asmr", label: "ASMR Stories Factory", icon: Moon },
  { href: "/cutting", label: "ASMR Cutting Studio", icon: Slice },
  { href: "/shorts", label: "Generated Shorts", icon: Clapperboard },
  { href: "/calendar", label: "Publishing Calendar", icon: CalendarDays },
  { href: "/accounts", label: "YouTube Accounts", icon: MonitorPlay },
  { href: "/media", label: "Media Library", icon: Library },
  { href: "/settings", label: "Settings", icon: Settings },
];
const MORE = [
  { href: "/projects", label: "All Projects", icon: FolderOpen },
  { href: "/captions", label: "Caption Templates", icon: Captions },
];

export function Sidebar() {
  const path = usePathname();
  const { jobs, connected } = useLive();
  const active = jobs.filter((j) => j.status === "running" || j.status === "queued").length;
  const isActive = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));
  const item = ({ href, label, icon: Icon }: (typeof NAV)[number], small = false) => (
    <Link
      key={href}
      href={href}
      className={cn(
        "flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-sidebar-foreground/75 transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground",
        small && "py-1.5 text-xs",
        isActive(href) && "bg-sidebar-accent text-sidebar-foreground font-medium",
      )}
    >
      <Icon className={cn("size-4", small && "size-3.5", isActive(href) && "text-primary")} />
      {label}
    </Link>
  );

  return (
    <>
      <aside className="hidden md:flex w-64 shrink-0 flex-col border-r border-sidebar-border bg-sidebar h-screen sticky top-0">
        <div className="flex items-center gap-2.5 px-5 h-16 border-b border-sidebar-border">
          <div className="size-8 rounded-lg bg-primary grid place-items-center font-black text-primary-foreground text-sm">P</div>
          <div className="leading-tight">
            <div className="font-bold tracking-wide text-sm">PODSYU</div>
            <div className="text-[11px] text-muted-foreground">Local AI content factory</div>
          </div>
        </div>
        <nav className="flex-1 p-3 space-y-0.5 overflow-y-auto">
          {NAV.map((n) => item(n))}
          <p className="px-3 pt-4 pb-1 text-[10px] uppercase tracking-wider text-muted-foreground/70">More</p>
          {MORE.map((n) => item(n, true))}
        </nav>
        <div className="p-4 border-t border-sidebar-border text-xs text-muted-foreground space-y-1.5">
          <div className="flex items-center gap-2">
            <span className={cn("size-2 rounded-full", connected ? "bg-emerald-400" : "bg-red-500 animate-pulse")} />
            {connected ? "Backend connected" : "Backend offline"}
          </div>
          {active > 0 && <div className="text-primary">{active} job{active > 1 ? "s" : ""} in queue</div>}
        </div>
      </aside>
      <nav className="md:hidden flex gap-1 overflow-x-auto border-b bg-sidebar px-2 py-2 sticky top-0 z-30">
        {[...NAV, ...MORE].map(({ href, label, icon: Icon }) => (
          <Link
            key={href}
            href={href}
            aria-label={label}
            className={cn("flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs whitespace-nowrap", isActive(href) ? "bg-sidebar-accent text-foreground" : "text-muted-foreground")}
          >
            <Icon className="size-3.5" />
            {label}
          </Link>
        ))}
      </nav>
    </>
  );
}
