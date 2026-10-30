export type Role = "candidate" | "employer";
export type User = { id: string; email: string; role: Role };
export type Job = {
  id: string;
  employer_id: string;
  title: string;
  description: string;
  location: string | null;
  employment_type: "full_time" | "part_time" | "contract";
  is_active: boolean;
};

export type Application = {
  id: string;
  job_id: string;
  candidate_id: string;
  candidate_email: string
  status: string;
  created_at: string;
};
