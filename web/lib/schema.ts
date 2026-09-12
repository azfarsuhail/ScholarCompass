import { z } from "zod";

/**
 * ProfileSchema — the contract for everything the student tells us.
 *
 * It has to hold two very different inputs to the same standard:
 *   1. an LLM's extraction of a PDF, which can return anything, and
 *   2. whatever the student types afterwards.
 *
 * Parsing the extraction through this schema BEFORE it reaches
 * `defaultValues` is the point. An unvalidated payload that sets
 * degree_level: "Bachelors" would put the select into a value it has no option
 * for — the field silently renders blank and the student submits a profile
 * missing the one constraint the matcher never relaxes.
 *
 * Everything is optional on purpose. Blank means "do not filter on this", and
 * that is a legitimate answer for every field here; requiring a value would
 * force students to invent one.
 */

export const DEGREE_LEVELS = ["bachelor", "master", "phd", "postdoc"] as const;

export const FIELD_TAGS = [
  "engineering",
  "computer science",
  "medicine",
  "economics",
  "public policy",
  "agriculture",
  "environment",
  "law",
  "physics",
  "chemistry",
  "biology",
  "arts and humanities",
  "education",
  "social sciences",
  "mathematics",
] as const;

/** "" from an empty input must become undefined, not NaN or 0. */
const optionalNumber = (min: number, max: number, message: string) =>
  z
    .union([z.string(), z.number()])
    .optional()
    .transform((v) => {
      if (v === "" || v === undefined || v === null) return undefined;
      const n = typeof v === "number" ? v : Number(v);
      return Number.isFinite(n) ? n : undefined;
    })
    .refine((n) => n === undefined || (n >= min && n <= max), { message });

export const ProfileSchema = z.object({
  full_name: z.string().max(120).optional().or(z.literal("")),

  passport_iso3: z
    .string()
    .optional()
    .or(z.literal(""))
    .transform((v) => (v ? v.toUpperCase() : v))
    .refine((v) => !v || /^[A-Z]{3}$/.test(v), {
      message: "Use a 3-letter country code, like PAK",
    }),

  // Never relaxed by the matcher, so a wrong value here hides every eligible
  // scholarship rather than merely reordering results.
  degree_level: z.enum(DEGREE_LEVELS).optional(),

  institution: z.string().max(160).optional().or(z.literal("")),

  fields_of_study: z.array(z.enum(FIELD_TAGS)).default([]),

  gpa_4: optionalNumber(0, 4, "GPA must be between 0 and 4"),

  // How we got the GPA, which decides whether the matcher applies tolerance.
  // A scanned 2.95 and a typed 2.95 are different claims.
  gpa_source: z.enum(["user", "ocr"]).default("user"),
  gpa_confidence: z.number().min(0).max(1).optional(),

  graduation_year: optionalNumber(1950, 2100, "Enter a four-digit year"),
  age: optionalNumber(15, 80, "Enter an age between 15 and 80"),

  // Chevening asks for 2,800 hours and rejects below it, so this is one of the
  // few numbers here that can actually exclude a scholarship. Blank still
  // means "not stated", which the matcher treats as eligible rather than zero.
  work_experience_hours: optionalNumber(0, 100000, "Enter hours between 0 and 100,000"),

  ielts: optionalNumber(0, 9, "IELTS is scored 0–9"),

  funding_preference: z.enum(["full", "any"]).default("any"),

  skills: z.array(z.string().max(60)).max(30).default([]),

  experience: z
    .array(
      z.object({
        role: z.string().max(120).default(""),
        organisation: z.string().max(120).default(""),
        period: z.string().max(60).nullable().optional(),
      }),
    )
    .max(10)
    .default([]),
});

export type ProfileValues = z.input<typeof ProfileSchema>;
export type ParsedProfile = z.output<typeof ProfileSchema>;

/**
 * The server's extraction payload.
 *
 * Deliberately permissive — this describes what the model MIGHT send, and its
 * job is to fail softly. `.catch()` on each field means one malformed value
 * degrades that field to empty instead of throwing away an otherwise good
 * extraction, which on a hackathon demo is the difference between a filled
 * form and a blank one.
 */
export const ExtractedProfileSchema = z.object({
  full_name: z.string().nullish().catch(null),
  institution: z.string().nullish().catch(null),
  degree_level: z.enum(DEGREE_LEVELS).nullish().catch(null),
  field_of_study: z.array(z.string()).nullish().catch([]),
  gpa_raw: z.string().nullish().catch(null),
  gpa_4: z.number().nullish().catch(null),
  gpa_confidence: z.number().nullish().catch(null),
  graduation_year: z.number().nullish().catch(null),
  skills: z.array(z.string()).nullish().catch([]),
  experience: z
    .array(
      z.object({
        role: z.string().nullish().catch(""),
        organisation: z.string().nullish().catch(""),
        period: z.string().nullish().catch(null),
      }),
    )
    .nullish()
    .catch([]),
  languages: z.array(z.string()).nullish().catch([]),
});

export type ExtractedProfile = z.infer<typeof ExtractedProfileSchema>;

export const emptyProfile: ProfileValues = {
  full_name: "",
  passport_iso3: "",
  degree_level: undefined,
  institution: "",
  fields_of_study: [],
  gpa_4: "",
  gpa_source: "user",
  graduation_year: "",
  age: "",
  work_experience_hours: "",
  ielts: "",
  funding_preference: "full",
  skills: [],
  experience: [],
};

/**
 * Map a validated extraction onto form values.
 *
 * Unknown field tags are dropped rather than passed through: the checkbox
 * group only renders FIELD_TAGS, so an unrecognised tag would be invisible in
 * the UI yet still submitted — a value the student was never shown and cannot
 * remove.
 */
export function extractionToFormValues(
  extracted: ExtractedProfile,
  current: ProfileValues,
): ProfileValues {
  const tags = (extracted.field_of_study ?? [])
    .map((f) => f.toLowerCase().trim())
    .filter((f): f is (typeof FIELD_TAGS)[number] =>
      (FIELD_TAGS as readonly string[]).includes(f),
    );

  return {
    ...current,
    full_name: extracted.full_name ?? current.full_name ?? "",
    institution: extracted.institution ?? current.institution ?? "",
    degree_level: extracted.degree_level ?? current.degree_level,
    fields_of_study: tags.length ? tags : (current.fields_of_study ?? []),
    gpa_4: extracted.gpa_4 != null ? String(extracted.gpa_4) : (current.gpa_4 ?? ""),
    // Marks the number as machine-read, which the matcher uses to forgive a
    // small shortfall rather than hiding a scholarship over a scan artefact.
    gpa_source: extracted.gpa_4 != null ? "ocr" : "user",
    gpa_confidence: extracted.gpa_confidence ?? undefined,
    graduation_year:
      extracted.graduation_year != null
        ? String(extracted.graduation_year)
        : (current.graduation_year ?? ""),
    skills: (extracted.skills ?? []).slice(0, 30),
    experience: (extracted.experience ?? []).slice(0, 10).map((e) => ({
      role: e.role ?? "",
      organisation: e.organisation ?? "",
      period: e.period ?? null,
    })),
  };
}

/**
 * Display label for a field tag.
 *
 * The stored values stay lowercase because they are matched against the
 * catalogue's own lowercase tags; only the rendering is capitalised. Keeping
 * the two apart means a UI copy change can never silently break matching.
 */
export function fieldLabel(tag: string): string {
  // Word-initial only. A bare /[a-z]/g uppercases every letter and the
  // checkboxes end up reading "ENGINEERING".
  return tag
    .split(" ")
    .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
    .join(" ");
}
