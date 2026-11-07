"use client";

import { createContext, useContext, useEffect, useRef, useState } from "react";
import { API, type Job, type Publication } from "./api";

type Live = { jobs: Job[]; publications: Publication[]; connected: boolean; version: number };
const Ctx = createContext<Live>({ jobs: [], publications: [], connected: false, version: 0 });

/** Real-time job/upload progress pushed by the backend over WebSocket (auto-reconnects). */
export function LiveProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<Live>({ jobs: [], publications: [], connected: false, version: 0 });
  const retry = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    const connect = () => {
      ws = new WebSocket(API.replace(/^http/, "ws") + "/api/ws");
      ws.onopen = () => setState((s) => ({ ...s, connected: true }));
      ws.onmessage = (e) => {
        const data = JSON.parse(e.data);
        setState((s) => ({ jobs: data.jobs, publications: data.publications, connected: true, version: s.version + 1 }));
      };
      ws.onclose = () => {
        setState((s) => ({ ...s, connected: false }));
        if (!closed) retry.current = setTimeout(connect, 2000);
      };
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(retry.current);
      ws?.close();
    };
  }, []);

  return <Ctx.Provider value={state}>{children}</Ctx.Provider>;
}

export const useLive = () => useContext(Ctx);

/** Calls `onChange` whenever a job or upload for the matching scope finishes or changes state. */
export function useLiveRefresh(onChange: () => void, match?: (j: Job) => boolean) {
  const { jobs, publications } = useLive();
  const key =
    jobs.filter((j) => !match || match(j)).map((j) => `${j.id}:${j.status}:${j.stage}`).join() +
    "|" + publications.map((p) => `${p.id}:${p.status}`).join();
  const cb = useRef(onChange);
  useEffect(() => {
    cb.current = onChange;
  });
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    cb.current();
  }, [key]);
}
