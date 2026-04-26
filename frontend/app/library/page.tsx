"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Masthead } from "../../components/Masthead";
import { Colophon } from "../../components/Colophon";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

type LibraryItem = {
  id: string;
  created_at: string;
  title: string | null;
  address: string | null;
  listing_url: string | null;
  voice_style: string | null;
  max_photos: number | null;
  raw_photo_count: number | null;
  selected_unique_photo_count: number | null;
  video_rel_path: string;
};

type LibraryResponse = { items: LibraryItem[] };

function formatDate(iso: string): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      day: "2-digit",
      month: "short",
      year: "numeric"
    });
  } catch {
    return iso;
  }
}

function shortId(id: string): string {
  return id.length > 8 ? id.slice(0, 8) : id;
}

function hostFromUrl(url: string | null): string | null {
  if (!url) return null;
  try {
    return new URL(url).host.replace(/^www\./, "");
  } catch {
    return null;
  }
}

export default function LibraryPage() {
  const [items, setItems] = useState<LibraryItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const response = await fetch(`${API_BASE}/api/library`, { cache: "no-store" });
        if (!response.ok) {
          throw new Error(`Server returned ${response.status} ${response.statusText}`.trim());
        }
        const data: LibraryResponse = await response.json();
        if (!cancelled) setItems(data.items || []);
      } catch (err) {
        if (cancelled) return;
        const message =
          err instanceof TypeError
            ? `Could not reach the API at ${API_BASE}. Is the backend running?`
            : err instanceof Error
              ? err.message
              : "Unknown error";
        setError(message);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const count = items?.length ?? 0;

  return (
    <main className="page">
      <div className="grain" aria-hidden />

      <div className="frame">
        <Masthead active="library" />

        <section className="library" id="library">
          <div className="section-head reveal">
            <span className="folio">
              Archive · Library {items ? <>· <span className="mono">{String(count).padStart(2, "0")}</span></> : null}
            </span>
            <h2>
              Your <em>walkthroughs.</em>
            </h2>
            <p>
              Every video the studio has rendered is filed here. Generations are
              kept locally on disk — nothing is uploaded.
            </p>
          </div>

          {error ? (
            <div className="alert" role="alert">
              <strong>Could not load the library</strong>
              {error}
            </div>
          ) : !items ? (
            <div className="empty-card reveal">
              <em>Reading the archive</em>
              One moment while we gather your files…
            </div>
          ) : items.length === 0 ? (
            <div className="empty-card reveal">
              <em>The shelf is empty</em>
              Generate your first walkthrough on the{" "}
              <Link
                href="/#create"
                style={{ color: "var(--olive)", textDecoration: "underline", textUnderlineOffset: 3 }}
              >
                home page
              </Link>{" "}
              and it will appear here automatically.
            </div>
          ) : (
            <div className="library-grid">
              {items.map((item, idx) => (
                <LibraryCard key={item.id} item={item} index={idx} />
              ))}
            </div>
          )}
        </section>

        <Colophon />
      </div>
    </main>
  );
}

function LibraryCard({ item, index }: { item: LibraryItem; index: number }) {
  const videoSrc = `${API_BASE}/generated/${item.video_rel_path}`;
  const date = useMemo(() => formatDate(item.created_at), [item.created_at]);
  const host = hostFromUrl(item.listing_url);
  const title = (item.title || item.address || "Untitled walkthrough").trim();

  return (
    <article
      className="library-card reveal"
      style={{ animationDelay: `${Math.min(index, 8) * 60}ms` }}
    >
      <div className="library-card-media">
        <video
          controls
          preload="metadata"
          playsInline
          src={`${videoSrc}#t=0.1`}
        />
      </div>

      <div className="library-card-body">
        <div className="library-card-meta">
          <span>{date}</span>
          <em>#{shortId(item.id)}</em>
        </div>

        <h3 className="library-card-title">{title}</h3>

        {item.address && item.address !== title ? (
          <p className="library-card-address">{item.address}</p>
        ) : null}

        {item.voice_style ? (
          <p className="library-card-voice">
            <span className="library-card-voice-label">Voice</span>
            {item.voice_style}
          </p>
        ) : null}

        <div className="library-card-footer">
          <span>
            {(item.selected_unique_photo_count ?? "—")}{" "}
            <span className="library-card-footer-sub">/ {item.raw_photo_count ?? "—"} frames</span>
          </span>
          {host ? (
            <a className="library-card-source" href={item.listing_url ?? "#"} target="_blank" rel="noreferrer">
              {host} ↗
            </a>
          ) : (
            <span className="library-card-source">Local</span>
          )}
        </div>
      </div>
    </article>
  );
}
