"use client";

import { FormEvent, useEffect, useRef, useState } from "react";

type Message = { role: "user" | "assistant"; content: string };

type Props = {
  apiBase: string;
  propertyContext: Record<string, unknown> | null;
};

function buildWelcome(hasListing: boolean): string {
  if (hasListing) {
    return (
      "I load your listing link again on each question and run a quick web search so answers can include " +
      "price, comps, and market context when the sites expose it. Results depend on what the page and search return. " +
      "Educational only—not legal, tax, or investment advice."
    );
  }
  return "Ask about buying, selling, offers, inspections, or staging. Generate a video from a URL to load a specific listing into this chat.";
}

export function PropertyChat({ apiBase, propertyContext }: Props) {
  const hasListing = Boolean(propertyContext);
  const contextKey = propertyContext
    ? String((propertyContext as { job_id?: string }).job_id ?? JSON.stringify(propertyContext).slice(0, 40))
    : "none";
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setMessages([{ role: "assistant", content: buildWelcome(hasListing) }]);
    setError(null);
  }, [contextKey, hasListing]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = input.trim();
    if (!text || loading) return;
    setInput("");
    setError(null);
    const history: Message[] = [...messages, { role: "user", content: text }];
    setMessages(history);
    setLoading(true);
    try {
      const response = await fetch(`${apiBase}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: history,
          property_context: propertyContext ?? undefined
        })
      });
      if (!response.ok) {
        let detail = `Request failed (${response.status})`;
        try {
          const body = await response.json();
          if (body && typeof body.detail === "string") {
            detail = body.detail;
          }
        } catch {
          /* ignore */
        }
        throw new Error(detail);
      }
      const data: { reply: string } = await response.json();
      setMessages((prev) => [...prev, { role: "assistant", content: data.reply }]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="property-chat">
      {hasListing ? (
        <p className="property-chat-badge">
          <span>Listing context loaded</span>
        </p>
      ) : (
        <p className="property-chat-hint">No listing attached — general questions only until you generate from a URL.</p>
      )}
      <div className="property-chat-transcript" role="log" aria-live="polite">
        {messages.map((m, i) => (
          <div key={`${i}-${m.role}`} className={`property-chat-bubble property-chat-bubble--${m.role}`}>
            {m.content}
          </div>
        ))}
        {loading ? (
          <div className="property-chat-bubble property-chat-bubble--assistant property-chat-typing" aria-hidden>
            …
          </div>
        ) : null}
        <div ref={bottomRef} />
      </div>
      {error ? (
        <div className="form-error" role="alert" style={{ margin: "0 0 10px" }}>
          {error}
        </div>
      ) : null}
      <form className="property-chat-form" onSubmit={onSubmit}>
        <label htmlFor="property-chat-input" className="visually-hidden">
          Message
        </label>
        <textarea
          id="property-chat-input"
          rows={2}
          value={input}
          placeholder="Ask about this home or real estate in general…"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              (e.target as HTMLTextAreaElement).form?.requestSubmit();
            }
          }}
          disabled={loading}
        />
        <button type="submit" className="property-chat-send" disabled={loading || !input.trim()}>
          Send
        </button>
      </form>
    </div>
  );
}
