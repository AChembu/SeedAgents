"use client";

import { FormEvent, useMemo, useState } from "react";

type JobStatus = "queued" | "running" | "completed" | "failed";

type JobView = {
  id: string;
  status: JobStatus;
  progress?: string | null;
  error?: string | null;
  artifacts?: Record<string, unknown>;
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";
const POLL_INTERVAL_MS = 3000;
const MAX_JOB_WAIT_MS = 8 * 60 * 1000;

const STAGES = [
  { num: "I",   key: "survey",  label: "Survey",  sub: "Scrape listing",   match: ["scrap", "fetch", "queue", "list"] },
  { num: "II",  key: "select",  label: "Select",  sub: "Curate frames",    match: ["frame", "select", "photo", "image"] },
  { num: "III", key: "narrate", label: "Narrate", sub: "Draft script",     match: ["narrat", "voice", "script", "copy"] },
  { num: "IV",  key: "animate", label: "Animate", sub: "Motion clips",     match: ["motion", "anim", "keyframe", "polish", "seedance"] },
  { num: "V",   key: "compose", label: "Compose", sub: "Render video",     match: ["compos", "render", "video", "encode", "mux", "audio"] }
];

function activeStageIndex(status: JobStatus, progress?: string | null) {
  if (status === "queued") return 0;
  if (status === "completed") return STAGES.length;
  if (status === "failed") return -1;
  const p = (progress || "").toLowerCase();
  for (let i = STAGES.length - 1; i >= 0; i--) {
    if (STAGES[i].match.some((k) => p.includes(k))) return i;
  }
  return 0;
}

async function getJob(jobId: string): Promise<JobView> {
  const response = await fetch(`${API_BASE}/api/jobs/${jobId}`, { cache: "no-store" });
  if (!response.ok) throw new Error("Failed to fetch job");
  return response.json();
}

export default function HomePage() {
  const [listingUrl, setListingUrl] = useState("");
  const [address, setAddress] = useState("");
  const [voiceStyle, setVoiceStyle] = useState("friendly luxury real-estate tour");
  const [maxPhotos, setMaxPhotos] = useState(8);
  const [job, setJob] = useState<JobView | null>(null);
  const [loading, setLoading] = useState(false);

  const resultVideo = useMemo(() => {
    const value = job?.artifacts?.video_rel_path;
    if (typeof value !== "string") return "";
    return `${API_BASE}/generated/${value}`;
  }, [job]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setJob(null);
    try {
      const response = await fetch(`${API_BASE}/api/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          listing_url: listingUrl || undefined,
          address: address || undefined,
          voice_style: voiceStyle,
          max_photos: maxPhotos
        })
      });
      if (!response.ok) throw new Error("Failed to queue generation");
      const created: JobView = await response.json();
      setJob(created);

      let current = created;
      const deadline = Date.now() + MAX_JOB_WAIT_MS;
      while (current.status === "queued" || current.status === "running") {
        if (Date.now() >= deadline) {
          setJob({
            ...current,
            status: "failed",
            error: "Job timed out while waiting for external providers. Please retry."
          });
          break;
        }
        await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
        current = await getJob(created.id);
        setJob(current);
      }
    } catch (error) {
      setJob({
        id: "n/a",
        status: "failed",
        error: error instanceof Error ? error.message : "Unknown error"
      });
    } finally {
      setLoading(false);
    }
  }

  const stageIdx = job ? activeStageIndex(job.status, job.progress) : -1;
  const progressPct =
    stageIdx < 0 ? 0 : Math.min(100, (Math.max(0, stageIdx) / (STAGES.length - 1)) * 100);

  const rawPhotoCount = job?.artifacts?.raw_photo_count;
  const selectedPhotoCount = job?.artifacts?.selected_unique_photo_count;

  return (
    <main className="page">
      <div className="grain" aria-hidden />

      <div className="frame">
        {/* ---------- MASTHEAD ---------- */}
        <header className="masthead reveal">
          <a className="brand" href="#top" aria-label="SeedEstate Field Studio">
            <span className="brand-mark">
              <SeedlingMark />
            </span>
            <span className="brand-text">
              <span className="brand-name">
                Seed<em>Estate</em>
              </span>
              <span className="brand-sub">Field Studio · Vol. I</span>
            </span>
          </a>

          <nav className="nav" aria-label="Primary">
            <a href="#studio">Studio</a>
            <a href="#worksheet">Worksheet</a>
            <a href="#dossier">Dossier</a>
          </nav>

          <span className="masthead-meta">Local · Live · MMXXV</span>
        </header>

        {/* ---------- HERO ---------- */}
        <section className="hero" id="studio">
          <div className="hero-text reveal" style={{ animationDelay: "60ms" }}>
            <span className="eyebrow">Vol. I — Real-estate walkthroughs</span>

            <h1 className="hero-title">
              Listings, told <em>like</em> stories.
            </h1>

            <p className="hero-lede">
              Hand the agent a URL or an address. It surveys photographs, drafts
              narration in your voice, polishes keyframes, animates a walkthrough,
              and lays it down with sound — a field guide, rendered.
            </p>

            <ul className="hero-meta">
              {STAGES.map((s) => (
                <li key={s.key}>
                  <span className="meta-num">{s.num}</span>
                  {s.label}
                </li>
              ))}
            </ul>
          </div>

          <div className="hero-art reveal" style={{ animationDelay: "180ms" }}>
            <FieldEmblem />
            <span className="hero-leaf hero-leaf--tl" aria-hidden>
              <LeafGlyph />
            </span>
            <span className="hero-leaf hero-leaf--br" aria-hidden>
              <LeafGlyph />
            </span>
          </div>
        </section>

        {/* ---------- WORKSHEET ---------- */}
        <section className="worksheet" id="worksheet">
          <div className="section-head reveal">
            <span className="folio">Worksheet № 01</span>
            <h2>
              Compose a <em>walkthrough.</em>
            </h2>
            <p>
              Fields with hairlines accept input. Direction is open — be specific
              about voice, pace, and audience. Defaults work well.
            </p>
          </div>

          <form className="ledger reveal" style={{ animationDelay: "120ms" }} onSubmit={onSubmit}>
            <div className="ledger-row">
              <div className="label-block">
                <label htmlFor="listing">Listing URL</label>
                <span className="label-num">i.</span>
              </div>
              <div className="field-block">
                <input
                  id="listing"
                  placeholder="https://www.zillow.com/homedetails/…"
                  value={listingUrl}
                  onChange={(event) => setListingUrl(event.target.value)}
                  autoComplete="off"
                  spellCheck={false}
                />
                <span className="ledger-hint">Zillow · Redfin · Compass · MLS</span>
              </div>
            </div>

            <div className="ledger-row">
              <div className="label-block">
                <label htmlFor="address">Address fallback</label>
                <span className="label-num">ii.</span>
              </div>
              <div className="field-block">
                <input
                  id="address"
                  placeholder="123 Main Street, San Francisco, CA"
                  value={address}
                  onChange={(event) => setAddress(event.target.value)}
                  autoComplete="off"
                />
                <span className="ledger-hint">Used only if the URL field is empty.</span>
              </div>
            </div>

            <div className="ledger-row">
              <div className="label-block">
                <label htmlFor="voice">Narration direction</label>
                <span className="label-num">iii.</span>
              </div>
              <div className="field-block">
                <textarea
                  id="voice"
                  rows={3}
                  value={voiceStyle}
                  onChange={(event) => setVoiceStyle(event.target.value)}
                />
                <span className="ledger-hint">
                  Tone, pace, audience. e.g. <em>warm, conversational, mid-tempo, family buyers.</em>
                </span>
              </div>
            </div>

            <div className="ledger-row">
              <div className="label-block">
                <label htmlFor="maxPhotos">Frames</label>
                <span className="label-num">iv.</span>
              </div>
              <div className="field-block">
                <div className="counter">
                  <button
                    type="button"
                    aria-label="Decrease frames"
                    disabled={maxPhotos <= 4}
                    onClick={() => setMaxPhotos((n) => Math.max(4, n - 1))}
                  >
                    −
                  </button>
                  <span className="counter-value">
                    <span className="num">{maxPhotos}</span>
                    <span className="of">of twelve</span>
                  </span>
                  <button
                    type="button"
                    aria-label="Increase frames"
                    disabled={maxPhotos >= 12}
                    onClick={() => setMaxPhotos((n) => Math.min(12, n + 1))}
                  >
                    +
                  </button>
                </div>
                <span className="ledger-hint">Between four and twelve unique stills.</span>
              </div>
            </div>

            <div className="submit-row">
              <button type="submit" className="primary" disabled={loading}>
                {loading ? (
                  <span className="primary-loading">
                    <span className="primary-spinner" aria-hidden /> Generating
                  </span>
                ) : (
                  <>
                    <span>Begin generation</span>
                    <ArrowGlyph />
                  </>
                )}
              </button>
              <span className="submit-meta">
                Typical render takes four to seven minutes — local, no telemetry.
              </span>
            </div>
          </form>
        </section>

        {/* ---------- DOSSIER ---------- */}
        <section className="dossier" id="dossier">
          <div className="section-head reveal">
            <span className="folio">
              Dossier {job ? <>№ <span className="mono">{job.id.slice(0, 8)}</span></> : "№ —"}
            </span>
            <h2>
              Field <em>report.</em>
            </h2>
            <p>
              Each generation runs through five stages. The pipeline below tracks
              progress in real time; artifacts and the final cut are filed beneath.
            </p>
          </div>

          {job ? (
            <>
              <div className="pipeline reveal">
                <div className="pipeline-header">
                  <span>Pipeline · Stages I–V</span>
                  <span>
                    Currently <em>{job.progress || job.status}</em>
                  </span>
                </div>
                <div
                  className="pipeline-track"
                  style={{ ["--progress" as string]: `calc((100% - 18%) * ${progressPct / 100})` }}
                >
                  {STAGES.map((s, i) => {
                    let cls = "";
                    if (job.status === "failed" && i === Math.max(0, stageIdx === -1 ? 0 : stageIdx)) {
                      cls = "failed";
                    } else if (job.status === "completed" || i < stageIdx) {
                      cls = "done";
                    } else if (i === stageIdx && job.status !== "queued") {
                      cls = "active";
                    } else if (i === 0 && job.status === "queued") {
                      cls = "active";
                    }
                    return (
                      <div key={s.key} className={`pipeline-step ${cls}`}>
                        <div className="pipeline-node">{s.num}</div>
                        <div className="pipeline-label">{s.label}</div>
                        <div className="pipeline-sublabel">{s.sub}</div>
                      </div>
                    );
                  })}
                </div>
              </div>

              <div className="dossier-grid">
                <div className="data-pair">
                  <span className="data-pair-label">Status</span>
                  <span className={`badge ${job.status}`}>{job.status}</span>
                </div>
                <div className="data-pair">
                  <span className="data-pair-label">Progress note</span>
                  <span className="data-pair-value italic">{job.progress || "—"}</span>
                </div>
                <div className="data-pair">
                  <span className="data-pair-label">Job identifier</span>
                  <span className="data-pair-value mono">{job.id}</span>
                </div>
                {typeof rawPhotoCount === "number" ? (
                  <div className="data-pair">
                    <span className="data-pair-label">Frames selected</span>
                    <span className="data-pair-value">
                      {String(selectedPhotoCount ?? 0)}{" "}
                      <span className="mono" style={{ fontSize: 13, color: "var(--ink-3)" }}>
                        / {String(rawPhotoCount)} raw
                      </span>
                    </span>
                  </div>
                ) : null}
              </div>

              {job.error ? (
                <div className="alert">
                  <strong>Generation halted</strong>
                  {job.error}
                </div>
              ) : null}

              {job.status === "completed" && resultVideo ? (
                <figure className="cut">
                  <div className="cut-frame">
                    <video controls>
                      <source src={resultVideo} type="video/mp4" />
                    </video>
                  </div>
                  <figcaption>
                    <span>Final cut · Filed locally</span>
                    <em>{new Date().toLocaleDateString(undefined, { day: "2-digit", month: "long", year: "numeric" })}</em>
                  </figcaption>
                </figure>
              ) : null}
            </>
          ) : (
            <div className="empty-card reveal">
              <em>No active job</em>
              Submit a worksheet above and the dossier will populate here.
            </div>
          )}
        </section>

        {/* ---------- COLOPHON ---------- */}
        <footer className="colophon">
          <span>SeedEstate Studio</span>
          <span className="dot">·</span>
          <em>Field-grown listings, narrated kindly.</em>
          <span className="colophon-meta">Built locally · No telemetry · MMXXV</span>
        </footer>
      </div>
    </main>
  );
}

/* ============================================================
   SVG components
   ============================================================ */

function SeedlingMark() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M12 22 V11" stroke="#1A1F12" strokeWidth="1.1" strokeLinecap="round" />
      <path
        d="M12 14 C 7.5 14, 5.5 11, 5 6.5 C 9.5 7.2, 11.2 9.5, 12 14 Z"
        fill="#3E4A2A"
      />
      <path
        d="M12 16 C 16.5 16, 18.5 13, 19 8.5 C 14.5 9.2, 12.8 11.5, 12 16 Z"
        fill="#6E7E47"
      />
      <path d="M7 22 H 17" stroke="#1A1F12" strokeWidth="0.8" strokeLinecap="round" opacity="0.5" />
    </svg>
  );
}

function ArrowGlyph() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M4 12 H 20" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
      <path d="M14 6 L 20 12 L 14 18" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" fill="none" />
    </svg>
  );
}

function LeafGlyph() {
  return (
    <svg viewBox="0 0 60 60" fill="none" aria-hidden style={{ width: "100%", height: "100%" }}>
      <path
        d="M8 52 C 8 28, 28 8, 52 8 C 52 32, 32 52, 8 52 Z"
        fill="#6E7E47"
        opacity="0.55"
      />
      <path
        d="M8 52 C 22 38, 38 22, 52 8"
        stroke="#3E4A2A"
        strokeWidth="0.8"
        strokeLinecap="round"
      />
    </svg>
  );
}

function FieldEmblem() {
  const ringText =
    "SEEDESTATE · FIELD STUDIO · NARRATED LISTINGS · EST. MMXXV · ";
  return (
    <svg viewBox="0 0 460 460" fill="none" aria-hidden>
      <defs>
        <path
          id="ringTextPath"
          d="M 230 230 m -190 0 a 190 190 0 1 1 380 0 a 190 190 0 1 1 -380 0"
        />
      </defs>

      {/* Outer dotted ring */}
      <circle
        cx="230"
        cy="230"
        r="218"
        stroke="#3E4A2A"
        strokeWidth="0.8"
        strokeDasharray="2 5"
        opacity="0.45"
      />

      {/* Inner ring */}
      <circle cx="230" cy="230" r="200" stroke="#3E4A2A" strokeWidth="0.8" opacity="0.35" />

      {/* Rotating text ring */}
      <g className="ring-text">
        <text
          fontFamily='"JetBrains Mono", ui-monospace, monospace'
          fontSize="11"
          letterSpacing="6"
          fill="#3E4A2A"
          opacity="0.85"
        >
          <textPath href="#ringTextPath" startOffset="0%">
            {ringText.repeat(3)}
          </textPath>
        </text>
      </g>

      {/* Compass marks */}
      <g stroke="#3E4A2A" strokeWidth="0.8" opacity="0.45">
        <line x1="230" y1="6" x2="230" y2="22" />
        <line x1="230" y1="438" x2="230" y2="454" />
        <line x1="6" y1="230" x2="22" y2="230" />
        <line x1="438" y1="230" x2="454" y2="230" />
      </g>
      <text
        x="230"
        y="4"
        textAnchor="middle"
        fontFamily='"JetBrains Mono", monospace'
        fontSize="9"
        fill="#3E4A2A"
        opacity="0.6"
      >
        N
      </text>

      {/* Inner illustration: house growing from a seed */}
      <g transform="translate(230 244)">
        {/* Soil hairline */}
        <line x1="-110" y1="86" x2="110" y2="86" stroke="#3E4A2A" strokeWidth="0.8" opacity="0.6" />
        <line
          x1="-110"
          y1="92"
          x2="110"
          y2="92"
          stroke="#3E4A2A"
          strokeWidth="0.6"
          strokeDasharray="2 4"
          opacity="0.4"
        />

        {/* Stem */}
        <path d="M 0 86 Q 0 50 0 12" stroke="#3E4A2A" strokeWidth="1.2" fill="none" />

        {/* Two leaves on stem */}
        <path
          d="M 0 56 C -34 50 -46 36 -52 14 C -28 14 -10 28 0 56 Z"
          fill="#6E7E47"
          opacity="0.85"
        />
        <path
          d="M 0 44 C 34 38 46 24 52 4 C 28 2 10 18 0 44 Z"
          fill="#3E4A2A"
          opacity="0.85"
        />

        {/* Roots below soil */}
        <g stroke="#3E4A2A" strokeWidth="0.8" fill="none" opacity="0.55">
          <path d="M 0 92 Q -8 104 -22 112" />
          <path d="M 0 92 Q 8 106 26 114" />
          <path d="M 0 92 Q 0 110 0 122" />
          <path d="M 0 92 Q -16 100 -34 102" />
          <path d="M 0 92 Q 18 100 38 104" />
        </g>

        {/* House on top (architectural elevation) */}
        <g transform="translate(-58 -120)" stroke="#1A1F12" strokeLinejoin="round">
          {/* Body */}
          <path
            d="M 0 70 L 0 38 L 58 0 L 116 38 L 116 70 Z"
            fill="#FBF7EC"
            strokeWidth="1.3"
          />
          {/* Roof line */}
          <path
            d="M 0 38 L 58 0 L 116 38"
            fill="none"
            strokeWidth="1.3"
          />
          {/* Door */}
          <path d="M 38 70 V 46 H 56 V 70" fill="#F1ECDD" strokeWidth="1.1" />
          <circle cx="52" cy="58" r="0.9" fill="#1A1F12" />
          {/* Window */}
          <path d="M 72 46 H 90 V 60 H 72 Z" fill="#F1ECDD" strokeWidth="1" />
          <path d="M 81 46 V 60 M 72 53 H 90" strokeWidth="0.6" opacity="0.6" />
          {/* Chimney */}
          <path d="M 88 14 V 4 H 96 V 19" fill="#FBF7EC" strokeWidth="1.1" />
          {/* Tiny vine creeping up */}
          <path
            d="M 0 70 C 6 60 4 50 10 44 C 14 40 12 32 18 28"
            fill="none"
            stroke="#3E4A2A"
            strokeWidth="0.8"
            opacity="0.7"
          />
          <circle cx="10" cy="44" r="2.4" fill="#6E7E47" opacity="0.85" />
          <circle cx="18" cy="28" r="2" fill="#6E7E47" opacity="0.85" />
        </g>

        {/* Ground markers */}
        <g fill="#3E4A2A" opacity="0.55">
          <circle cx="-92" cy="86" r="1.4" />
          <circle cx="92" cy="86" r="1.4" />
        </g>
      </g>

      {/* Bottom caption arc */}
      <text
        x="230"
        y="448"
        textAnchor="middle"
        fontFamily='"Fraunces", serif'
        fontStyle="italic"
        fontSize="13"
        fill="#3E4A2A"
        opacity="0.85"
      >
        a field guide to your listing
      </text>
    </svg>
  );
}
