export type Level = "R0" | "R1" | "R2" | "R3" | "R4" | "R5";

export type Scholarship = {
  id: string;
  slug: string;
  title: string;
  provider: string | null;
  host_country_iso3: string | null;
  fields_of_study: string[];
  min_gpa_4: number | null;
  funding_type: string | null;
  deadline: string | null;
  is_rolling: boolean;
  source_url: string;
  /** Set when the publisher states a deadline policy rather than a date
   *  (DAAD: "deadlines are updated annually"). Distinguishes "announced
   *  later" from "we could not find one". */
  deadline_note?: string | null;
  /** Bare domain for the Brandfetch logo hotlink (never an image URL). */
  provider_domain?: string | null;
  min_work_experience_hours?: number | null;
  return_obligation?: string | null;
  entry_requirement?: string | null;
};

export type MatchEvent = {
  index: number;
  level: Level;
  is_exact: boolean;
  gaps: string[];
  notes: string[];
  scholarship: Scholarship;
};

export type Enrichment = {
  index: number;
  score: number;
  rationale: string;
  matched_criteria: string[];
  gaps: string[];
};

export type RunEvent = {
  run_id: string;
  relaxation_level: Level;
  level_counts: Record<string, number>;
  candidate_count: number;
  deterministic_ms: number;
};

/**
 * How each rung is described to a student.
 *
 * Never "R3" — a relaxation level is an internal detail. What the student
 * needs is what it would take, stated plainly. Colour is always paired with
 * this text, never used alone to carry the meaning.
 */
export const LEVEL_LABEL: Record<Level, { label: string; tone: string }> = {
  R0: { label: "Exact match", tone: "exact" },
  R1: { label: "Partial funding", tone: "near" },
  R2: { label: "Needs a test score", tone: "near" },
  R3: { label: "Slightly above your GPA", tone: "stretch" },
  R4: { label: "Closed — next cycle", tone: "stretch" },
  R5: { label: "Outside your field", tone: "stretch" },
};
