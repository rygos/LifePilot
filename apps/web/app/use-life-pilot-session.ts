"use client";

import { useCallback, useEffect, useState } from "react";

export function useLifePilotSession(api: string) {
  const [token, setToken] = useState("");
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [sessionMessage, setSessionMessage] = useState("");

  const clearSession = useCallback((message = "") => {
    localStorage.removeItem("lifepilot-token");
    setToken("");
    setIsAuthenticated(false);
    setSessionMessage(message);
  }, []);

  useEffect(() => {
    const saved = localStorage.getItem("lifepilot-token");
    if (saved) setToken(saved);
  }, []);

  useEffect(() => {
    if (!token) {
      setIsAuthenticated(false);
      return;
    }

    localStorage.setItem("lifepilot-token", token);
    const controller = new AbortController();
    void fetch(`${api}/api/auth/me`, { headers: { Authorization: `Bearer ${token}` }, signal: controller.signal })
      .then(response => {
        if (response.status === 401) {
          clearSession("Deine Sitzung ist abgelaufen. Bitte melde dich erneut an.");
          return;
        }
        if (!response.ok) throw new Error("Anmeldung konnte nicht geprüft werden.");
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

  async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await fetch(`${api}${path}`, { ...init, headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}), ...init.headers } });
    if (response.status === 401 && token) {
      clearSession("Deine Sitzung ist abgelaufen. Bitte melde dich erneut an.");
      throw new Error("Deine Sitzung ist abgelaufen. Bitte melde dich erneut an.");
    }
    if (!response.ok) throw new Error((await response.json()).detail ?? "Anfrage fehlgeschlagen");
    return response.status === 204 ? undefined as T : response.json();
  }

  return { token, setToken, isAuthenticated, sessionMessage, clearSession, request };
}
