"use client";

import { useCallback, useSyncExternalStore } from "react";

import type { Scholarship } from "@/lib/types";

/**
 * Saved scholarships, in the browser only.
 *
 * Deliberately NOT the PRD's `POST /v1/matches/compare`. Comparing is a
 * private act of deliberation, and the whole privacy posture here is that we
 * hold as little about a student as possible — a shortlist sent to the server
 * would be a new, durable statement of intent attached to a session id, in
 * exchange for a feature that works perfectly without one.
 *
 * `useSyncExternalStore` rather than `useState` + an effect: the toggle lives
 * on every card and the panel lives beside the list, so they need one shared
 * source of truth, and this is the React-sanctioned way to read an external
 * one without tearing during concurrent renders. It also gives us a correct
 * SSR snapshot for free, which a naive `localStorage` read during render does
 * not.
 */

const KEY = "sc.favorites.v1";

/** Bounded so a shortlist stays comparable and localStorage stays small. */
export const MAX_FAVORITES = 8;

/**
 * A snapshot, not a reference.
 *
 * Storing ids alone would mean an empty panel after a reload or a re-search,
 * because the result set is streamed fresh each time and the old rows are
 * gone. These are the fields the compare table actually renders.
 */
export type SavedScholarship = Pick<
  Scholarship,
  | "id"
  | "slug"
  | "title"
  | "provider"
  | "host_country_iso3"
  | "fields_of_study"
  | "min_gpa_4"
  | "funding_type"
  | "deadline"
  | "is_rolling"
  | "source_url"
  | "provider_domain"
  | "deadline_note"
  | "last_verified_at"
> & { saved_at: string };

export type ToggleResult = "added" | "removed" | "full";

// Cached so getSnapshot returns a STABLE reference. Returning a freshly parsed
// array each call makes useSyncExternalStore re-render forever.
let cache: SavedScholarship[] | null = null;
const listeners = new Set<() => void>();

/** Stable identity for the server/hydration snapshot, for the same reason. */
const EMPTY: SavedScholarship[] = [];

function read(): SavedScholarship[] {
  if (cache) return cache;
  try {
    const raw = window.localStorage.getItem(KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    cache = Array.isArray(parsed) ? (parsed as SavedScholarship[]) : [];
  } catch {
    // Private mode, blocked site data, or corrupt JSON. An unusable store is
    // an empty one — never a thrown render.
    cache = [];
  }
  return cache;
}

function write(next: SavedScholarship[]): void {
  cache = next;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    // Quota or a blocked store. The in-memory copy still drives this tab, so
    // the feature degrades to session-lifetime rather than breaking.
  }
  listeners.forEach((l) => l());
}

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange);
  // Another tab edited the shortlist: drop the cache so the next snapshot
  // re-reads, then notify.
  const onStorage = (e: StorageEvent) => {
    if (e.key === KEY) {
      cache = null;
      onChange();
    }
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(onChange);
    window.removeEventListener("storage", onStorage);
  };
}

function snapshot(scholarship: Scholarship): SavedScholarship {
  return {
    id: scholarship.id,
    slug: scholarship.slug,
    title: scholarship.title,
    provider: scholarship.provider,
    host_country_iso3: scholarship.host_country_iso3,
    fields_of_study: scholarship.fields_of_study,
    min_gpa_4: scholarship.min_gpa_4,
    funding_type: scholarship.funding_type,
    deadline: scholarship.deadline,
    is_rolling: scholarship.is_rolling,
    source_url: scholarship.source_url,
    provider_domain: scholarship.provider_domain,
    deadline_note: scholarship.deadline_note,
    last_verified_at: scholarship.last_verified_at,
    saved_at: new Date().toISOString(),
  };
}

export function useFavorites() {
  const items = useSyncExternalStore(subscribe, read, () => EMPTY);

  const toggle = useCallback((scholarship: Scholarship): ToggleResult => {
    const current = read();
    if (current.some((s) => s.id === scholarship.id)) {
      write(current.filter((s) => s.id !== scholarship.id));
      return "removed";
    }
    // Refuse rather than silently evicting someone's oldest pick.
    if (current.length >= MAX_FAVORITES) return "full";
    write([...current, snapshot(scholarship)]);
    return "added";
  }, []);

  const remove = useCallback((id: string) => {
    write(read().filter((s) => s.id !== id));
  }, []);

  const clear = useCallback(() => write([]), []);

  return {
    items,
    count: items.length,
    isFull: items.length >= MAX_FAVORITES,
    has: useCallback((id: string) => items.some((s) => s.id === id), [items]),
    toggle,
    remove,
    clear,
  };
}
