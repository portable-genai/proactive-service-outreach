"use client";

import { useEffect, useState } from "react";

// Every request goes to THIS origin. The browser never learns the service's address and never
// holds its credential; the route handler under /api/agent forwards, having discarded whatever
// identity the client tried to assert.
const API = "/api/agent";

// Mirrors the service's seeded local personas. The picker is a DEV convenience: the server
// validates the selection against its own list, so a hand-crafted value cannot invent a persona.
const PERSONAS = ["analyst", "approver", "auditor", "other-tenant"];

interface CardSummary {
  name?: string;
  description?: string;
  skills?: { id: string; name: string }[];
}

// The five operational events this service watches for. The list mirrors the trigger rules in
// config/settings.yaml; the server refuses anything outside it with 422, so a hand-crafted value
// cannot invent an event type.
const EVENT_TYPES = [
  "failed_payment",
  "delivery_exception",
  "expiring_card",
  "fraud_hold",
  "outage",
];

// A recent instant, because the service decides against the wall clock: an operational event is
// only news for as long as its configured window. There is deliberately no "decide as at" field
// anywhere in this UI, because quiet hours turn on that instant and it is the service's to
// choose, never the caller's.
function minutesAgo(minutes: number) {
  return new Date(Date.now() - minutes * 60_000).toISOString();
}

export default function Home() {
  const [persona, setPersona] = useState(PERSONAS[0]);
  const [eventType, setEventType] = useState(EVENT_TYPES[0]);
  const [subjectId, setSubjectId] = useState("subj-000101");
  const [market, setMarket] = useState("SG");
  const [attributes, setAttributes] = useState('{"card_suffix": "4242", "retry_on": "2026-08-11"}');
  const [detail, setDetail] = useState("Issuer declined the authorisation.");
  const [result, setResult] = useState("");
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [card, setCard] = useState<CardSummary | null>(null);

  // The service names itself, so this UI carries no hardcoded product name to go stale.
  useEffect(() => {
    let live = true;
    fetch(API + "/.well-known/agent-card.json", { cache: "no-store" })
      .then((response) => (response.ok ? response.json() : null))
      .then((body) => {
        if (live) setCard(body as CardSummary | null);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setFailed(false);
    try {
      let parsedAttributes: Record<string, string> = {};
      try {
        parsedAttributes = JSON.parse(attributes) as Record<string, string>;
      } catch {
        setFailed(true);
        setResult("Attributes must be a JSON object of name to value.");
        setBusy(false);
        return;
      }
      const response = await fetch(API + "/v1/outreach/evaluate", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Dev-Persona": persona },
        body: JSON.stringify({
          event_id: "evt-ui-" + Date.now(),
          event_type: eventType,
          subject_id: subjectId,
          occurred_at: minutesAgo(5),
          market,
          locale: market === "JP" ? "ja-JP" : market === "AU" ? "en-AU" : "en-SG",
          detail,
          attributes: parsedAttributes,
        }),
      });
      const body = await response.text();
      setFailed(!response.ok);
      setResult(body);
    } catch (error) {
      setFailed(true);
      setResult(String(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <h1>{card?.name ?? "Agent console"}</h1>
      <p className="sub">
        {card?.description ??
          "Submit an operational event. Whether the customer is contacted is decided by pure code, and a consequential result is held for a human rather than sent."}
      </p>

      <form onSubmit={submit}>
        <fieldset>
          <legend>Who you are</legend>
          <label>
            Seeded dev persona (local profile only; the server resolves identity, not this field)
            <select value={persona} onChange={(event) => setPersona(event.target.value)}>
              {PERSONAS.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>
        </fieldset>

        <fieldset>
          <legend>The operational event</legend>
          <label>
            Event type
            <select value={eventType} onChange={(event) => setEventType(event.target.value)}>
              {EVENT_TYPES.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Subject id (a pseudonymous key, never a name)
            <input value={subjectId} onChange={(event) => setSubjectId(event.target.value)} />
          </label>
          <label>
            Market
            <select value={market} onChange={(event) => setMarket(event.target.value)}>
              {["SG", "AU", "JP"].map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Facts the message may quote (JSON)
            <textarea value={attributes} onChange={(event) => setAttributes(event.target.value)} />
          </label>
          <label>
            Source-system detail (redacted before anything else happens)
            <textarea value={detail} onChange={(event) => setDetail(event.target.value)} />
          </label>
          <button type="submit" disabled={busy}>
            {busy ? "Working" : "Decide this event"}
          </button>
        </fieldset>
      </form>

      {result ? <pre className={failed ? "result error" : "result"}>{result}</pre> : null}

      <footer>
        Synthetic, obviously fictional data only. Identity and tenant are resolved server-side
        and the client-asserted actor is discarded; see ui/README.md for the embedding contract.
        The response carries the whole decision: which trigger fired, the consent decision id,
        the cap counters, the quiet-hours window and every reason that refused.
      </footer>
    </main>
  );
}
