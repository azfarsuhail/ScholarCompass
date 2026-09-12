"use client";

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { api, ApiError } from "@/lib/api";
import { ExtractedProfileSchema, type ExtractedProfile } from "@/lib/schema";

type UploadResponse = {
  document_id: string;
  pages: number;
  ocr_confidence: number;
  grade: { gpa_4: number | null; percentage: number | null; confidence: number } | null;
  profile: unknown;
  needs_confirmation: boolean;
  text_layer: boolean;
};

const ACCEPT = "application/pdf,image/png,image/jpeg,image/webp";

export function DocumentUpload({
  onExtracted,
  onGrade,
  onParsingChange,
}: {
  onExtracted: (profile: ExtractedProfile) => void;
  onGrade: (gpa: number, confidence: number) => void;
  onParsingChange: (parsing: boolean) => void;
}) {
  const reduced = useReducedMotion();
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  async function upload(file: File) {
    setBusy(true);
    setError(null);
    setStatus(null);
    onParsingChange(true);

    const body = new FormData();
    body.append("file", file);

    try {
      const res = await api<UploadResponse>("/v1/documents?kind=resume&country=PK", {
        method: "POST",
        body,
      });

      // Validate before it touches the form. An unchecked payload can put the
      // degree select into a value it has no option for, which renders blank
      // and silently drops the one constraint the matcher never relaxes.
      const parsed = ExtractedProfileSchema.safeParse(res.profile);
      if (parsed.success) {
        onExtracted(parsed.data);
        setStatus(
          res.text_layer
            ? "Read directly from the PDF's text layer — no guesswork."
            : "Read by OCR. Please double-check the values.",
        );
      } else if (res.grade?.gpa_4 != null) {
        onGrade(res.grade.gpa_4, res.grade.confidence);
        setStatus("We found a grade but could not read the rest. Fill in what's missing.");
      } else {
        setStatus("We couldn't pull anything usable out of that. Fill the form in below.");
      }
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 413
          ? "That file is over 10MB. Try a smaller file."
          : e instanceof ApiError && e.status === 415
            ? "Upload a PDF or an image (PNG, JPEG)."
            : "We could not read that file. You can fill the form in by hand.",
      );
    } finally {
      setBusy(false);
      onParsingChange(false);
    }
  }

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        const f = e.dataTransfer.files?.[0];
        if (f) void upload(f);
      }}
      className={[
        "rounded-xl border border-dashed p-lg transition-colors duration-200",
        dragging ? "border-accent-blue bg-surface-2" : "border-hairline bg-surface-1",
      ].join(" ")}
    >
      <h2 className="fr-headline text-ink">Start from your CV or transcript</h2>
      <p className="fr-body-sm mt-xxs text-ink-muted">
        We read it, fill the form in, and discard the file — it is never stored.
        Drag it here or choose a file. PDF or image, up to 10MB.
      </p>

      {/* The real input stays in the accessibility tree (sr-only, not hidden)
          so it remains keyboard- and screen-reader-reachable. */}
      <input
        ref={inputRef}
        id="document"
        type="file"
        accept={ACCEPT}
        className="sr-only"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) void upload(f);
        }}
      />

      <div className="mt-md flex flex-wrap items-center gap-sm">
        <Button
          type="button"
          variant="outline"
          disabled={busy}
          className="fr-btn-secondary"
          onClick={() => inputRef.current?.click()}
        >
          {busy ? "Reading…" : "Choose a file"}
        </Button>
        <span className="fr-body-sm text-ink-muted">or skip and type it in below</span>
      </div>

      <p className="sr-only" role="status" aria-live="polite">
        {busy ? "Reading your document" : (status ?? "")}
      </p>

      <AnimatePresence>
        {busy && (
          <motion.div
            initial={reduced ? false : { opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="overflow-hidden"
          >
            <div className="mt-md flex items-center gap-sm border-t border-hairline-soft pt-md">
              <motion.span
                aria-hidden="true"
                className="size-2 rounded-full bg-accent-blue"
                animate={reduced ? {} : { scale: [1, 1.6, 1], opacity: [1, 0.4, 1] }}
                transition={{ duration: 1.1, repeat: Infinity, ease: "easeInOut" }}
              />
              <p className="fr-body-sm text-ink-muted">
                Extracting your education, skills and experience…
              </p>
            </div>
          </motion.div>
        )}

        {!busy && status && (
          <motion.p
            initial={reduced ? false : { opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="fr-body-sm mt-md border-t border-hairline-soft pt-md text-success"
          >
            {status}
          </motion.p>
        )}
      </AnimatePresence>

      {error && (
        <p role="alert" className="fr-body-sm mt-md text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
