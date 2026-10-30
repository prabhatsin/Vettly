"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";
import { homeFor, login } from "@/lib/auth";

export default function Register() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("candidate");
  const [error, setError] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await api("/auth/register", {
        method: "POST",
        body: JSON.stringify({ email, password, role }),
      });
      const user = await login(email, password);
      router.replace(homeFor(user.role));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <main className="mx-auto mt-20 max-w-sm p-4">
      <h1 className="mb-4 text-2xl font-semibold">Register</h1>
      <form onSubmit={submit} className="flex flex-col gap-3">
        <input className="rounded border p-2" type="email" placeholder="Email" required
          value={email} onChange={(e) => setEmail(e.target.value)} />
        <input className="rounded border p-2" type="password" placeholder="Password (min 8)" required minLength={8}
          value={password} onChange={(e) => setPassword(e.target.value)} />
        <select className="rounded border p-2" value={role} onChange={(e) => setRole(e.target.value)}>
          <option value="candidate">Candidate</option>
          <option value="employer">Employer</option>
        </select>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button className="rounded bg-black p-2 text-white">Create account</button>
      </form>
      <p className="mt-3 text-sm">
        Have an account? <Link className="underline" href="/login">Log in</Link>
      </p>
    </main>
  );
}