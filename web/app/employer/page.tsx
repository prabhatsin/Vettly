"use client";
import { useCallback, useEffect, useState } from "react";
import Nav from "@/components/Nav";
import { api } from "@/lib/api";
import { useUser } from "@/lib/auth";
import type { Application, Job } from "@/lib/types";

export default function Employer() {
  const user = useUser("employer");
  const [jobs, setJobs] = useState<Job[]>([]);
  const [apps, setApps] = useState<Record<string, Application[]>>({});
  const [form, setForm] = useState({
    title: "", description: "", location: "", employment_type: "full_time",
  });
  const [error, setError] = useState("");

  const load = useCallback(
    () => api<Job[]>("/jobs/mine").then(setJobs).catch((e) => setError(e.message)),
    []
  );
  useEffect(() => {
    if (user) load();
  }, [user, load]);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await api("/jobs", {
        method: "POST",
        body: JSON.stringify({ ...form, location: form.location || null }),
      });
      setForm({ title: "", description: "", location: "", employment_type: "full_time" });
      load();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function toggle(job: Job) {
    if (job.is_active) await api(`/jobs/${job.id}`, { method: "DELETE" });
    else await api(`/jobs/${job.id}`, { method: "PUT", body: JSON.stringify({ is_active: true }) });
    load();
  }

  async function showApps(jobId: string) {
    const list = await api<Application[]>(`/jobs/${jobId}/applications`);
    setApps((prev) => ({ ...prev, [jobId]: list }));
  }

  if (!user) return null;
  return (
    <>
      <Nav user={user} />
      <main className="mx-auto max-w-2xl p-4">
        <h1 className="mb-4 text-2xl font-semibold">Post a job</h1>
        <form onSubmit={create} className="mb-8 flex flex-col gap-3">
          <input className="rounded border p-2" placeholder="Title" required minLength={3}
            value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          <textarea className="rounded border p-2" placeholder="Description (min 10 chars)" required minLength={10}
            value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          <input className="rounded border p-2" placeholder="Location (optional)"
            value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} />
          <select className="rounded border p-2" value={form.employment_type}
            onChange={(e) => setForm({ ...form, employment_type: e.target.value })}>
            <option value="full_time">Full time</option>
            <option value="part_time">Part time</option>
            <option value="contract">Contract</option>
          </select>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <button className="rounded bg-black p-2 text-white">Create job</button>
        </form>

        <h2 className="mb-3 text-xl font-semibold">My jobs</h2>
        <ul className="flex flex-col gap-3">
          {jobs.map((j) => (
            <li key={j.id} className="rounded border p-3">
              <div className="flex items-center justify-between">
                <span className="font-medium">
                  {j.title} {!j.is_active && <em className="text-sm text-gray-500">(closed)</em>}
                </span>
                <span className="flex gap-3 text-sm">
                  <button className="underline" onClick={() => showApps(j.id)}>Applicants</button>
                  <button className="underline" onClick={() => toggle(j)}>
                    {j.is_active ? "Close" : "Reopen"}
                  </button>
                </span>
              </div>
              {apps[j.id] && (
                <ul className="mt-2 border-t pt-2 text-sm">
                  {apps[j.id].length === 0 && <li>No applicants yet.</li>}
                  {apps[j.id].map((a) => (
                    <li key={a.id}>
                      Candidate {a.candidate_email} · {a.status} ·{" "}
                      {new Date(a.created_at).toLocaleDateString()}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      </main>
    </>
  );
}