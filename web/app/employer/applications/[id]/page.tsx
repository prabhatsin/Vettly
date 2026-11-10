"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Nav from "@/components/Nav";
import { api } from "@/lib/api";
import { useUser } from "@/lib/auth";
import type { Replay, ReportOut } from "@/lib/types";

export default function ReportPage() {
  const user = useUser("employer");
  const { id } = useParams<{ id: string }>();
  const [rep, setRep] = useState<ReportOut | null>(null);
  const [replay, setReplay] = useState<Replay | null>(null);
  const [active, setActive] = useState<number | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!user) return;
    api<ReportOut>(`/employer/applications/${id}/report`).then(setRep).catch((e) => setError(e.message));
    api<Replay>(`/employer/applications/${id}/replay`).then(setReplay).catch(() => {});
  }, [user, id]);

  function jump(turn: number) {
    setActive(turn);
    document.getElementById(`turn-${turn}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  async function rescore() {
    await api(`/employer/applications/${id}/rescore`, { method: "POST" });
    setRep(null);
    setTimeout(() => api<ReportOut>(`/employer/applications/${id}/report`).then(setRep), 20000);
  }

  if (!user) return null;
  const r = rep?.report;
  return (
    <>
      <Nav user={user} />
      <main className="mx-auto grid max-w-5xl gap-6 p-4 md:grid-cols-2">
        <section>
          <h1 className="mb-2 text-2xl font-semibold">Interview report</h1>
          {error && <p className="text-red-600">{error}</p>}
          {rep && !r && <p>Status: {rep.status}{rep.error ? ` · ${rep.error}` : ""}</p>}
          {r && (
            <>
              <p className="text-lg">
                Score {r.overall_score ?? "–"} · {r.recommendation} · coverage {Math.round(r.coverage * 100)}%
              </p>
              <p className="mb-3 text-sm text-gray-500">{r.advice_note}</p>
              {r.criteria.map((c) => (
                <div key={c.key} className="mb-3 rounded border p-3">
                  <div className="font-medium">{c.name}: {c.score ?? "–"}/5 <em className="text-xs text-gray-500">({c.status})</em></div>
                  <p className="text-sm">{c.reason}</p>
                  {c.evidence.map((e, i) => (
                    <button key={i} className="mt-1 block text-left text-sm italic underline" onClick={() => jump(e.turn)}>
                      “{e.quote}”
                    </button>
                  ))}
                </div>
              ))}
              {r.strengths.length > 0 && <><h2 className="font-semibold">Strengths</h2><ul className="mb-2 list-disc pl-5 text-sm">{r.strengths.map((s, i) => <li key={i}>{s}</li>)}</ul></>}
              {r.concerns.length > 0 && <><h2 className="font-semibold">Concerns</h2><ul className="list-disc pl-5 text-sm">{r.concerns.map((s, i) => <li key={i}>{s}</li>)}</ul></>}
            </>
          )}
          <button className="mt-4 rounded border px-3 py-1 text-sm" onClick={rescore}>Re-run scoring</button>
        </section>

        <section>
          <h2 className="mb-2 text-xl font-semibold">Transcript</h2>
          <div className="flex max-h-[80vh] flex-col gap-2 overflow-y-auto">
            {replay?.turns.map((t) => (
              <div key={t.index} id={`turn-${t.index}`}
                className={`rounded p-2 text-sm ${t.role === "candidate" ? "bg-gray-100" : "border"} ${active === t.index ? "ring-2 ring-yellow-400" : ""}`}>
                <b>{t.role === "candidate" ? "Candidate" : "Iris"}:</b> {t.text}
              </div>
            ))}
          </div>
        </section>
      </main>
    </>
  );
}