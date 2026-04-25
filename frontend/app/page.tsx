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

async function getJob(jobId: string): Promise<JobView> {
  const response = await fetch(`${API_BASE}/api/jobs/${jobId}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error("Failed to fetch job");
  }
  return response.json();
}

export default function HomePage() {
  const [listingUrl, setListingUrl] = useState("");
  const [address, setAddress] = useState("");
  const [voiceStyle, setVoiceStyle] = useState("friendly luxury real-estate tour");
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
          voice_style: voiceStyle
        })
      });
      if (!response.ok) {
        throw new Error("Failed to queue generation");
      }
      const created: JobView = await response.json();
      setJob(created);

      let current = created;
      while (current.status === "queued" || current.status === "running") {
        await new Promise((resolve) => setTimeout(resolve, 3000));
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

  return (
    <main className="container">
      <h1>SeedEstate Real-Estate Video Agent</h1>
      <p>
        Submit a listing URL or address. The agent scrapes photos and copy, drafts narration, polishes keyframes,
        generates walkthrough motion clips, and composes a narrated video.
      </p>

      <form className="card row" onSubmit={onSubmit}>
        <label htmlFor="listing">Listing URL</label>
        <input
          id="listing"
          placeholder="https://www.zillow.com/homedetails/..."
          value={listingUrl}
          onChange={(event) => setListingUrl(event.target.value)}
        />

        <label htmlFor="address">Address (optional fallback)</label>
        <input
          id="address"
          placeholder="123 Main St, San Francisco, CA"
          value={address}
          onChange={(event) => setAddress(event.target.value)}
        />

        <label htmlFor="voice">Voice style</label>
        <textarea id="voice" rows={3} value={voiceStyle} onChange={(event) => setVoiceStyle(event.target.value)} />

        <button type="submit" disabled={loading}>
          {loading ? "Generating..." : "Generate walkthrough"}
        </button>
      </form>

      {job ? (
        <section className="card row" style={{ marginTop: "1rem" }}>
          <h2>Status</h2>
          <div>ID: {job.id}</div>
          <div>Status: {job.status}</div>
          {job.progress ? <div>Progress: {job.progress}</div> : null}
          {job.error ? <div style={{ color: "#fca5a5" }}>Error: {job.error}</div> : null}

          {job.status === "completed" ? (
            <>
              <h3>Video output</h3>
              <p>The backend wrote the final video file in the generated folder.</p>
              {resultVideo ? (
                <video controls style={{ width: "100%", borderRadius: 10 }}>
                  <source src={resultVideo} type="video/mp4" />
                </video>
              ) : null}
            </>
          ) : null}
        </section>
      ) : null}
    </main>
  );
}
