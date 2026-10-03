"use client";

import { useSyncExternalStore } from "react";
import { DEFAULT_USER_ID } from "./types";

/**
 * The acting user (no auth in this POC). Stored in localStorage and sent as
 * X-User-Id. Server render always uses the default user.
 */
const STORAGE_KEY = "health-briefing.user-id";
const listeners = new Set<() => void>();

export function getCurrentUserId(): string {
  if (typeof window === "undefined") return DEFAULT_USER_ID;
  try {
    return window.localStorage.getItem(STORAGE_KEY) ?? DEFAULT_USER_ID;
  } catch {
    return DEFAULT_USER_ID;
  }
}

export function setCurrentUserId(id: string): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, id);
  } catch {
    // Storage unavailable (private mode); the choice lasts for this page only.
  }
  listeners.forEach((fn) => fn());
}

function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  const onStorage = (e: StorageEvent) => {
    if (e.key === STORAGE_KEY) fn();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(fn);
    window.removeEventListener("storage", onStorage);
  };
}

export function useCurrentUserId(): string {
  return useSyncExternalStore(subscribe, getCurrentUserId, () => DEFAULT_USER_ID);
}
