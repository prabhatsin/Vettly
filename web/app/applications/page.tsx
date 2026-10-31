"use client";
import { useEffect, useState } from "react";
import Nav from "@/components/Nav";
import { api } from "@/lib/api";
import { useUser } from "@/lib/auth";
import type { Application, Job } from "@/lib/types";
import Link from "next/link";

export default function Applications() {
  const user = useUser("candidate");
  const [apps, setApps] = useState<Application[]>([]);
  const [titles, setTitles] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!user) return;
    Promise.all([api<Application[]>("/applications/mine"), api<Job[]>("/jobs")]).then(
      ([a, jobs]) => {
        setApps(a);
        setTitles(Object.fromEntries(jobs.map((j) => [j.id, j.title])));
      }
    );
  }, [user]);

  if (!user) return null;
  return (
    <>
      <Nav user={user} />
      <main className="mx-auto max-w-2xl p-4">
        <h1 className="mb-4 text-2xl font-semibold">My applications</h1>
        {apps.length === 0 && <p>You haven't applied to anything yet.</p>}
        <ul className="flex flex-col gap-3">
          {apps.map((a) => (
              <li key={a.id} className="flex items-center justify-between rounded border p-3">
                <span>{titles[a.job_id] ?? `Job ${a.job_id.slice(0, 8)} (closed)`}</span>
                <span className="flex items-center gap-4 text-sm text-gray-600">
                  {a.status} · {new Date(a.created_at).toLocaleDateString()}
                  <Link
                    className="rounded bg-black px-3 py-1 text-white"
                    href={`/interview/${a.id}`}
                  >
                    Start interview
                  </Link>
                </span>
              </li>
          ))}
        </ul>
      </main>
    </>
  );
}