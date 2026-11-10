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

export type CandidateRow = {
  application_id: string;
  candidate_email: string;
  application_status: string;
  report_status: string | null;
  overall_score: number | null;
  recommendation: string | null;
};
export type Evidence = { turn: number; quote: string };
export type CriterionResult = {
  key: string; name: string; weight: number;
  status: "ok" | "unverified" | "failed";
  score: number | null; reason: string; evidence: Evidence[];
};
export type Report = {
  overall_score: number | null;
  recommendation: "hire" | "maybe" | "no_hire" | "insufficient_data";
  advice_note: string; coverage: number;
  criteria: CriterionResult[]; strengths: string[]; concerns: string[];
};
export type ReportOut = {
  application_id: string; status: string; error: string | null;
  report: Report | null; updated_at: string;
};
export type Replay = {
  turns: { index: number; role: string; text: string; seqs: number[] }[];
  evidence: { criterion_key: string; criterion_name: string; turn: number; quote: string }[];
};