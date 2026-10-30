"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import Nav from "@/components/Nav";
import { api } from "@/lib/api";
import { useUser } from "@/lib/auth";
import type { Job } from "@/lib/types";

export default function Jobs() {
  const user = useUser();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!user) return;
    api<Job[]>("/jobs").then(setJobs).catch((e) => setError(e.message));
  }, [user]);

  if (!user) return null;
  return (
    <>
      <Nav user={user} />
      <main className="mx-auto max-w-2xl p-4">
        <h1 className="mb-4 text-2xl font-semibold">Open jobs</h1>
        {error && <p className="text-red-600">{error}</p>}
        {jobs.length === 0 && !error && <p>No open jobs yet.</p>}
        <ul className="flex flex-col gap-3">
          {jobs.map((j) => (
            <li key={j.id} className="rounded border p-3">
              <Link className="font-medium underline" href={`/jobs/${j.id}`}>{j.title}</Link>
              <p className="text-sm text-gray-600">
                {j.location ?? "Remote"} · {j.employment_type.replace("_", " ")}
              </p>
            </li>
          ))}
        </ul>
      </main>
    </>
  );
}