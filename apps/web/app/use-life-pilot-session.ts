"use client";

import { useCallback, useEffect, useState } from "react";
import { rememberIdentity, forgetIdentity } from "../public/offline-store.mjs";

export type AuthenticatedUser = { id: string; username: string; role: "user" | "admin" };

export class ApiRequestError extends Error {
  readonly status: number;
  readonly hasServerDetail: boolean;

  constructor(status: number, message: string, hasServerDetail: boolean) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.hasServerDetail = hasServerDetail;
  }
}

export function useLifePilotSession(api: string) {
  const [token, setToken] = useState("");
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [sessionMessage, setSessionMessage] = useState("");
  const [currentUser, setCurrentUser] = useState<AuthenticatedUser | null>(null);

  const clearSession = useCallback((message = "") => {
    localStorage.removeItem("lifepilot-token");
    try { forgetIdentity(); } catch { /* offline storage may be unavailable */ }
    setToken("");
    setIsAuthenticated(false);
    setCurrentUser(null);
    setSessionMessage(message);
  }, []);

  useEffect(() => {
    const saved = localStorage.getItem("lifepilot-token");
    if (saved) setToken(saved);
    const changed = (event: StorageEvent) => { if (event.key === "lifepilot-token" || event.key === null) window.location.reload(); };
    window.addEventListener("storage", changed);
    return () => window.removeEventListener("storage", changed);
  }, []);

  useEffect(() => {
    if (!token) {
      setIsAuthenticated(false);
      setCurrentUser(null);
      return;
    }

    localStorage.setItem("lifepilot-token", token);
    const controller = new AbortController();
    void fetch(`${api}/api/auth/me`, { headers: { Authorization: `Bearer ${token}` }, signal: controller.signal })
      .then(async response => {
        if (response.status === 401) {
          clearSession("Deine Sitzung ist abgelaufen. Bitte melde dich erneut an.");
          return;
        }
        if (!response.ok) throw new Error("Anmeldung konnte nicht geprüft werden.");
        const user = await response.json() as AuthenticatedUser;
        if (controller.signal.aborted || localStorage.getItem("lifepilot-token") !== token) return;
        setCurrentUser(user);
        void rememberIdentity(api, user.id, token).catch(() => {});
        setSessionMessage("");
        setIsAuthenticated(true);
      })
      .catch(error => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setIsAuthenticated(false);
        setSessionMessage(error instanceof Error ? error.message : String(error));
      });

    const recheck = () => { if (!controller.signal.aborted) void fetch(`${api}/api/auth/me`, { headers: { Authorization: `Bearer ${token}` }, signal: controller.signal }).then(async response => {
      if (controller.signal.aborted || localStorage.getItem("lifepilot-token") !== token) return;
      if (response.status === 401) { clearSession("Deine Sitzung ist abgelaufen. Bitte melde dich erneut an."); return; }
      if (!response.ok) return;
      const user = await response.json() as AuthenticatedUser;
      if (controller.signal.aborted || localStorage.getItem("lifepilot-token") !== token) return;
      setCurrentUser(user); setIsAuthenticated(true); setSessionMessage("");
      void rememberIdentity(api,user.id,token).catch(() => {});
    }).catch(() => {}); };
    window.addEventListener("online",recheck);
    return () => { controller.abort(); window.removeEventListener("online",recheck); };
  }, [api, clearSession, token]);

  const request = useCallback(async <T,>(path: string, init: RequestInit = {}): Promise<T> => {
    const response = await fetch(`${api}${path}`, { ...init, headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}), ...init.headers } });
    if (response.status === 401 && token) {
      clearSession("Deine Sitzung ist abgelaufen. Bitte melde dich erneut an.");
      throw new Error("Deine Sitzung ist abgelaufen. Bitte melde dich erneut an.");
    }
    if (!response.ok) {
      const body = await response.text();
      let message = `Anfrage fehlgeschlagen (${response.status})`;
      let hasServerDetail = false;
      if (response.headers.get("content-type")?.includes("application/json")) {
        try {
          const parsed: unknown = JSON.parse(body);
          if (typeof parsed === "object" && parsed !== null && "detail" in parsed) {
            const detail = parsed.detail;
            message = typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map(item => typeof item === "object" && item !== null && "msg" in item ? String(item.msg) : String(item)).join(" · ") : message;
            hasServerDetail = true;
          }
        } catch (caught) {
          if (!(caught instanceof SyntaxError)) throw caught;
        }
      }
      throw new ApiRequestError(response.status, message, hasServerDetail);
    }
    return response.status === 204 ? undefined as T : response.json();
  }, [api, clearSession, token]);

  return { token, setToken, isAuthenticated, sessionMessage, clearSession, request, currentUser };
}
