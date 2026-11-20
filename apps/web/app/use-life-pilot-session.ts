"use client";

import { useCallback, useEffect, useState } from "react";

export type AuthenticatedUser = { id: string; username: string; role: "user" | "admin" };

export function useLifePilotSession(api: string) {
  const [token, setToken] = useState("");
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [sessionMessage, setSessionMessage] = useState("");
  const [currentUser, setCurrentUser] = useState<AuthenticatedUser | null>(null);

  const clearSession = useCallback((message = "") => {
    localStorage.removeItem("lifepilot-token");
    setToken("");
    setIsAuthenticated(false);
    setCurrentUser(null);
    setSessionMessage(message);
  }, []);

  useEffect(() => {
    const saved = localStorage.getItem("lifepilot-token");
    if (saved) setToken(saved);
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
        setCurrentUser(await response.json() as AuthenticatedUser);
        setSessionMessage("");
        setIsAuthenticated(true);
      })
      .catch(error => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setIsAuthenticated(false);
        setSessionMessage(error instanceof Error ? error.message : String(error));
      });

    return () => controller.abort();
  }, [api, clearSession, token]);

  const request = useCallback(async <T,>(path: string, init: RequestInit = {}): Promise<T> => {
    const response = await fetch(`${api}${path}`, { ...init, headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}), ...init.headers } });
    if (response.status === 401 && token) {
      clearSession("Deine Sitzung ist abgelaufen. Bitte melde dich erneut an.");
      throw new Error("Deine Sitzung ist abgelaufen. Bitte melde dich erneut an.");
    }
    if (!response.ok) throw new Error((await response.json()).detail ?? "Anfrage fehlgeschlagen");
    return response.status === 204 ? undefined as T : response.json();
  }, [api, clearSession, token]);

  return { token, setToken, isAuthenticated, sessionMessage, clearSession, request, currentUser };
}
