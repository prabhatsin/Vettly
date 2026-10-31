"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import Nav from "@/components/Nav";
import { api } from "@/lib/api";
import { useUser } from "@/lib/auth";
import type { Job } from "@/lib/types";

function JobDetailContent() {
  const { id } = useParams<{ id: string }>();
  const user = useUser();
  const [job, setJob] = useState<Job | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (!user || !id) return;
    api<Job>(`/jobs/${id}`).then(setJob).catch((e) => setError(e.message));
  }, [user, id]);

  async function apply(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setError("");
    const form = new FormData();
    form.append("resume", file);
    try {
      await api(`/jobs/${id}/apply`, { method: "POST", body: form });
      setDone(true);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  if (!user) return null;
  return (
    <>
      <Nav user={user} />
      <main className="mx-auto max-w-2xl p-4">
        {error && !job && <p className="text-red-600">{error}</p>}
        {job && (
          <>
            <h1 className="text-2xl font-semibold">{job.title}</h1>
            <p className="mb-3 text-sm text-gray-600">
              {job.location ?? "Remote"} · {job.employment_type.replace("_", " ")}
            </p>
            <p className="mb-6 whitespace-pre-wrap">{job.description}</p>

            {user.role === "candidate" && !done && (
              <form onSubmit={apply} className="flex flex-col gap-3 rounded border p-3">
                <label className="text-sm font-medium">Upload your résumé (PDF, max 5 MB)</label>
                <input type="file" accept="application/pdf" required
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
                {error && <p className="text-sm text-red-600">{error}</p>}
                <button className="rounded bg-black p-2 text-white">Apply</button>
              </form>
            )}
            {done && (
              <p className="rounded bg-green-100 p-3">
                Applied! See <Link className="underline" href="/applications">your applications</Link>.
              </p>
            )}
          </>
        )}
      </main>
    </>
  );
}

export default function JobDetail() {
  return (
    <Suspense fallback={<p className="p-4">Loading...</p>}>
      <JobDetailContent />
    </Suspense>
  );
}