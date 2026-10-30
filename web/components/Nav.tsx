"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { clearToken } from "@/lib/api";
import type { User } from "@/lib/types";

export default function Nav({ user }: { user: User }) {
  const router = useRouter();
  return (
    <nav className="flex items-center gap-4 border-b p-4 text-sm">
      <Link href="/jobs">Jobs</Link>
      {user.role === "candidate" && <Link href="/applications">My applications</Link>}
      {user.role === "employer" && <Link href="/employer">My jobs</Link>}
      <span className="ml-auto text-gray-500">
        {user.email} ({user.role})
      </span>
      <button
        className="underline"
        onClick={() => {
          clearToken();
          router.replace("/login");
        }}
      >
        Log out
      </button>
    </nav>
  );
}