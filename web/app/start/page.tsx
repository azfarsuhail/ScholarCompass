"use client";

import { motion } from "motion/react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { StepIndicator } from "@/components/StepIndicator";
import { TranscriptUpload } from "@/components/TranscriptUpload";
import { api } from "@/lib/api";

const FIELDS = [
  "engineering",
  "computer science",
  "economics",
  "public policy",
  "medicine",
  "agriculture",
];

const inputClass =
  "min-h-11 w-full rounded-sc border border-border bg-card px-3 text-card-foreground transition-colors duration-200 focus:border-accent";

export default function StartPage() {
  const router = useRouter();
  const [gpa, setGpa] = useState("");
  // Tracks whether the GPA came from OCR so the backend can apply the right
  // tolerance — a scanned 2.95 is not the same claim as a typed 2.95.
  const [gpaSource, setGpaSource] = useState<"user" | "ocr">("user");
  const [gpaConfidence, setGpaConfidence] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    const form = new FormData(e.currentTarget);
    const ielts = form.get("ielts");
    const age = form.get("age");

    try {
      await api("/v1/profile", {
        method: "PUT",
        body: JSON.stringify({
          passport_iso3: String(form.get("passport") || "").toUpperCase(),
          degree_level: form.get("degree_level"),
          fields_of_study: form.getAll("field").map(String),
          // Only send what was actually filled in — a blank field means
          // "do not filter on this", not zero.
          ...(gpa
            ? {
                gpa_4: Number(gpa),
                gpa_source: gpaSource,
                ...(gpaSource === "ocr" && gpaConfidence != null
                  ? { gpa_confidence: gpaConfidence }
                  : {}),
              }
            : {}),
          ...(age ? { age: Number(age) } : {}),
          ...(ielts ? { language_scores: { ielts: Number(ielts) } } : {}),
          funding_preference: form.get("funding") || "any",
        }),
      });
      router.push("/results");
    } catch {
      setError("Could not save your answers. Check your connection and retry.");
      setSaving(false);
    }
  }

  return (
    <main id="main" className="mx-auto w-full max-w-2xl flex-1 px-6 py-12">
      <StepIndicator current={0} />

      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
      >
        <h1 className="text-3xl font-bold text-balance">
          Tell us enough to filter, no more
        </h1>
        <p className="mt-2 text-muted-foreground">
          Every field is optional. Blank means “don’t filter on this” — we never
          guess a value you didn’t give us.
        </p>
      </motion.div>

      <div className="mt-8">
        <TranscriptUpload
          onGrade={(value, confidence) => {
            setGpa(value.toFixed(2));
            setGpaSource("ocr");
            setGpaConfidence(confidence);
          }}
        />
      </div>

      <form onSubmit={onSubmit} className="mt-8 flex flex-col gap-5">
        <div className="grid gap-5 sm:grid-cols-2">
          <div>
            <label htmlFor="passport" className="block font-bold">
              Passport country
            </label>
            <p id="passport-help" className="text-sm text-muted-foreground">
              3-letter code, e.g. PAK
            </p>
            <input
              id="passport"
              name="passport"
              aria-describedby="passport-help"
              maxLength={3}
              defaultValue="PAK"
              className={`${inputClass} mt-1 uppercase`}
            />
          </div>

          <div>
            <label htmlFor="degree_level" className="block font-bold">
              Studying for
            </label>
            <p id="degree-help" className="text-sm text-muted-foreground">
              Never relaxed — we won’t show other levels
            </p>
            <select
              id="degree_level"
              name="degree_level"
              aria-describedby="degree-help"
              defaultValue="master"
              className={`${inputClass} mt-1 cursor-pointer`}
            >
              <option value="bachelor">Bachelor’s</option>
              <option value="master">Master’s</option>
              <option value="phd">PhD</option>
              <option value="postdoc">Postdoc</option>
            </select>
          </div>

          <div>
            <label htmlFor="gpa_4" className="block font-bold">
              GPA (4.0 scale)
            </label>
            <p id="gpa-help" className="text-sm text-muted-foreground">
              {gpaSource === "ocr"
                ? "Read from your transcript — correct it if wrong"
                : "Leave blank if unsure — we won’t filter on it"}
            </p>
            <input
              id="gpa_4"
              name="gpa_4"
              type="number"
              step="0.01"
              min="0"
              max="4"
              value={gpa}
              onChange={(e) => {
                setGpa(e.target.value);
                // A hand-edit makes it the student's own claim, not ours.
                setGpaSource("user");
                setGpaConfidence(null);
              }}
              aria-describedby="gpa-help"
              className={`${inputClass} mt-1`}
            />
          </div>

          <div>
            <label htmlFor="ielts" className="block font-bold">
              IELTS score
            </label>
            <p id="ielts-help" className="text-sm text-muted-foreground">
              Blank is fine — shown as “needs a test score”
            </p>
            <input
              id="ielts"
              name="ielts"
              type="number"
              step="0.5"
              min="0"
              max="9"
              aria-describedby="ielts-help"
              className={`${inputClass} mt-1`}
            />
          </div>

          <div>
            <label htmlFor="age" className="block font-bold">
              Age
            </label>
            <input
              id="age"
              name="age"
              type="number"
              min="15"
              max="70"
              className={`${inputClass} mt-1`}
            />
          </div>

          <div>
            <label htmlFor="funding" className="block font-bold">
              Funding needed
            </label>
            <select
              id="funding"
              name="funding"
              defaultValue="full"
              className={`${inputClass} mt-1 cursor-pointer`}
            >
              <option value="full">Full funding</option>
              <option value="any">Any funding</option>
            </select>
          </div>
        </div>

        <fieldset>
          <legend className="font-bold">Fields of study</legend>
          <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1">
            {FIELDS.map((f) => (
              <label
                key={f}
                className="flex min-h-11 cursor-pointer items-center gap-2"
              >
                <input
                  type="checkbox"
                  name="field"
                  value={f}
                  defaultChecked={f === "engineering"}
                  className="size-4 cursor-pointer"
                />
                <span>{f}</span>
              </label>
            ))}
          </div>
        </fieldset>

        {error && (
          <p role="alert" className="rounded-sc border border-destructive p-3 text-destructive">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={saving}
          className="min-h-12 w-full cursor-pointer rounded-sc bg-accent px-6 font-bold text-on-accent transition-colors duration-200 hover:bg-primary hover:text-on-primary disabled:opacity-60 sm:w-auto sm:self-start"
        >
          {saving ? "Finding matches…" : "See my matches →"}
        </button>
      </form>
    </main>
  );
}
