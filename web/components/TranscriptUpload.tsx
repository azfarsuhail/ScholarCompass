"use client";

import { AnimatePresence, motion } from "motion/react";
import { useRef, useState } from "react";

import { api, ApiError } from "@/lib/api";

type UploadResult = {
  document_id: string;
  pages: number;
  ocr_confidence: number;
  grade: { gpa_4: number | null; percentage: number | null; confidence: number; note: string | null } | null;
  needs_confirmation: boolean;
};

/**
 * Optional transcript upload.
 *
 * Deliberately framed as a shortcut, never a requirement: OCR on a phone photo
 * of a transcript is genuinely unreliable, so the manual fields stay visible
 * and anything we read is presented for confirmation rather than applied
 * silently.
 */
export function TranscriptUpload({
  onGrade,
}: {
  onGrade: (gpa: number, confidence: number) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<UploadResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  async function upload(file: File) {
    setBusy(true);
    setError(null);
    setResult(null);
    const body = new FormData();
    body.append("file", file);

    try {
      const res = await api<UploadResult>("/v1/documents?kind=transcript", {
        method: "POST",
        body,
      });
      setResult(res);
      if (res.grade?.gpa_4 != null) {
        onGrade(res.grade.gpa_4, res.grade.confidence);
      }
    } catch (e) {
      const msg =
        e instanceof ApiError && e.status === 413
          ? "That file is over 10MB. Try a smaller scan."
          : e instanceof ApiError && e.status === 415
            ? "Upload a PDF or an image (PNG, JPEG)."
            : "We could not read that file. You can type your GPA instead.";
      setError(msg);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-sc border border-dashed border-border bg-card p-5">
      <h2 className="font-bold">Upload a transcript (optional)</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        We read the grade and discard the file — it is never stored. PDF or
        image, up to 10MB.
      </p>

      <input
        ref={inputRef}
        id="transcript"
        type="file"
        accept="application/pdf,image/png,image/jpeg,image/webp"
        className="sr-only"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) void upload(f);
        }}
      />

      <button
        type="button"
        disabled={busy}
        onClick={() => inputRef.current?.click()}
        className="mt-4 min-h-11 cursor-pointer rounded-sc border border-accent px-5 font-bold text-accent transition-colors duration-200 hover:bg-accent hover:text-on-accent disabled:opacity-60"
      >
        {busy ? "Reading…" : "Choose a file"}
      </button>

      <p className="sr-only" role="status" aria-live="polite">
        {busy ? "Reading your transcript" : result ? "Transcript read" : ""}
      </p>

      <AnimatePresence>
        {result && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
            className="overflow-hidden"
          >
            <div className="mt-4 border-t border-border pt-4 text-sm">
              {result.grade?.gpa_4 != null ? (
                <>
                  <p className="font-bold text-success">
                    We read your GPA as {result.grade.gpa_4.toFixed(2)} / 4.0
                    {result.grade.percentage
                      ? ` (${result.grade.percentage.toFixed(1)}%)`
                      : ""}
                  </p>
                  <p className="mt-1 text-muted-foreground">
                    {result.needs_confirmation
                      ? "We are not confident about this — please check the field below and correct it if it is wrong."
                      : "Filled in below. Change it if it does not look right."}
                  </p>
                </>
              ) : (
                <p className="text-warning">
                  We could not find a grade in that document. Type it in below
                  instead.
                </p>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {error && (
        <p role="alert" className="mt-4 text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
