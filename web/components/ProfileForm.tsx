"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useRouter } from "next/navigation";
import { useCallback, useRef, useState } from "react";
import { useFieldArray, useForm } from "react-hook-form";

import { DocumentUpload } from "@/components/DocumentUpload";
import { FormSkeleton } from "@/components/Skeleton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api } from "@/lib/api";
import { clearPassportCheck } from "@/lib/visa";
import {
  emptyProfile,
  extractionToFormValues,
  FIELD_TAGS,
  fieldLabel,
  ProfileSchema,
  type ExtractedProfile,
  type ProfileValues,
} from "@/lib/schema";

// DESIGN.md {components.text-input}: surface-1 ground, 10px/14px padding,
// rounded-md, blue level-3 focus ring. .fr-input also floors the height at
// 44px, which the documented 10px padding alone would miss.
const CONTROL = "fr-input";

const SPRING = { type: "spring" as const, stiffness: 320, damping: 30, mass: 0.8 };

export function ProfileForm() {
  const router = useRouter();
  const reduced = useReducedMotion();
  const [parsing, setParsing] = useState(false);
  const [autofilled, setAutofilled] = useState<string[]>([]);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const skillInputRef = useRef<HTMLInputElement>(null);

  const form = useForm<ProfileValues>({
    resolver: zodResolver(ProfileSchema),
    defaultValues: emptyProfile,
    // Validate on blur, not on every keystroke: a GPA field that shouts
    // "must be between 0 and 4" while you are still typing "3." is hostile.
    mode: "onBlur",
  });

  const { fields: experience, remove: removeExperience } = useFieldArray({
    control: form.control,
    name: "experience",
  });

  const skills = form.watch("skills") ?? [];
  const selectedFields = form.watch("fields_of_study") ?? [];

  /**
   * Fold an extraction into the form.
   *
   * reset() rather than a pile of setValue() calls: it swaps the whole value
   * tree in one commit, so React renders once instead of once per field, and
   * the form's dirty/touched state is re-based on the extracted values. That
   * matters — a student who then edits one field should have only that field
   * marked dirty.
   */
  const onExtracted = useCallback(
    (extracted: ExtractedProfile) => {
      const next = extractionToFormValues(extracted, form.getValues());
      form.reset(next, { keepDefaultValues: false });

      const filled: string[] = [];
      if (extracted.institution) filled.push("institution");
      if (extracted.degree_level) filled.push("degree_level");
      if (extracted.gpa_4 != null) filled.push("gpa_4");
      if (extracted.graduation_year) filled.push("graduation_year");
      if (extracted.field_of_study?.length) filled.push("fields_of_study");
      if (extracted.skills?.length) filled.push("skills");
      if (extracted.experience?.length) filled.push("experience");
      setAutofilled(filled);
    },
    [form],
  );

  async function onSubmit(values: ProfileValues) {
    setSubmitError(null);
    const parsed = ProfileSchema.parse(values);
    try {
      await api("/v1/profile", {
        method: "PUT",
        body: JSON.stringify({
          passport_iso3: parsed.passport_iso3 || undefined,
          degree_level: parsed.degree_level,
          fields_of_study: parsed.fields_of_study,
          ...(parsed.gpa_4 !== undefined
            ? {
                gpa_4: parsed.gpa_4,
                gpa_source: parsed.gpa_source,
                ...(parsed.gpa_source === "ocr" && parsed.gpa_confidence != null
                  ? { gpa_confidence: parsed.gpa_confidence }
                  : {}),
              }
            : {}),
          ...(parsed.age !== undefined ? { age: parsed.age } : {}),
          ...(parsed.ielts !== undefined
            ? { language_scores: { ielts: parsed.ielts } }
            : {}),
          funding_preference: parsed.funding_preference,
          institution: parsed.institution || undefined,
          skills: parsed.skills,
          experience: parsed.experience,
        }),
      });
      // The visa gate caches "does this session have a passport?" for the life
      // of the tab. Without this, a student who came back here to add one would
      // still be told it is missing — the SPA never remounts to re-read it.
      clearPassportCheck();
      router.push("/results");
    } catch {
      setSubmitError("Could not save your answers. Check your connection and retry.");
    }
  }

  const wasAutofilled = (name: string) => autofilled.includes(name);

  /** Highlights a field the extraction filled, so edits feel invited. */
  const fieldMotion = (name: string) =>
    reduced || !wasAutofilled(name)
      ? {}
      : {
          initial: { backgroundColor: "color-mix(in srgb, var(--sc-accent) 12%, transparent)" },
          animate: { backgroundColor: "rgba(0,0,0,0)" },
          transition: { duration: 1.2, ease: "easeOut" as const },
        };

  function addSkill() {
    const value = skillInputRef.current?.value.trim();
    if (!value) return;
    const current = form.getValues("skills") ?? [];
    if (!current.includes(value)) {
      form.setValue("skills", [...current, value].slice(0, 30), { shouldDirty: true });
    }
    if (skillInputRef.current) skillInputRef.current.value = "";
  }

  return (
    <div className="flex flex-col gap-xl">
      <DocumentUpload
        onParsingChange={setParsing}
        onExtracted={onExtracted}
        onGrade={(gpa, confidence) => {
          form.setValue("gpa_4", String(gpa), { shouldDirty: true });
          form.setValue("gpa_source", "ocr");
          form.setValue("gpa_confidence", confidence);
          setAutofilled((a) => (a.includes("gpa_4") ? a : [...a, "gpa_4"]));
        }}
      />

      {/* While the backend parses, the form is replaced by a skeleton of its
          own shape — so the layout does not jump when the real fields land. */}
      <AnimatePresence mode="wait" initial={false}>
        {parsing ? (
          <motion.div
            key="skeleton"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
          >
            <FormSkeleton />
          </motion.div>
        ) : (
          <motion.div
            key="form"
            initial={reduced ? false : { opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={SPRING}
          >
            <Form {...form}>
              <form onSubmit={form.handleSubmit(onSubmit)} className="flex flex-col gap-lg">
                {autofilled.length > 0 && (
                  <motion.p
                    initial={reduced ? false : { opacity: 0, y: -6 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={SPRING}
                    role="status"
                    className="fr-card fr-body-sm !p-md text-ink"
                  >
                    We filled in {autofilled.length} section
                    {autofilled.length === 1 ? "" : "s"} from your document.
                    Everything below is editable — correct anything we got wrong
                    before searching.
                  </motion.p>
                )}

                <div className="grid gap-lg sm:grid-cols-2">
                  <FormField
                    control={form.control}
                    name="full_name"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Name</FormLabel>
                        <FormDescription>Only used to address you. Never stored on a server you log into.</FormDescription>
                        <FormControl>
                          <motion.div {...fieldMotion("full_name")} className="rounded-sc">
                            <Input {...field} value={field.value ?? ""} className={CONTROL} autoComplete="name" />
                          </motion.div>
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="passport_iso3"
                    render={({ field }) => (
                      // Anchor target for the visa gate on a match card, which
                      // links here when the panel is opened without a passport.
                      // scroll-mt-xxl keeps the field off the viewport edge so
                      // its label and description land on screen with it.
                      <FormItem id="passport-country" className="scroll-mt-xxl">
                        <FormLabel>Passport country</FormLabel>
                        <FormDescription>3-letter code, e.g. PAK</FormDescription>
                        <FormControl>
                          <Input
                            {...field}
                            value={field.value ?? ""}
                            maxLength={3}
                            className={`${CONTROL} uppercase`}
                            autoComplete="country"
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="institution"
                    render={({ field }) => (
                      <FormItem className="sm:col-span-2">
                        <FormLabel>Institution</FormLabel>
                        <FormDescription>Where you study or studied most recently</FormDescription>
                        <FormControl>
                          <motion.div {...fieldMotion("institution")} className="rounded-sc">
                            <Input {...field} value={field.value ?? ""} className={CONTROL} />
                          </motion.div>
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="degree_level"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Studying for</FormLabel>
                        <FormDescription>Never relaxed — we won’t show other levels</FormDescription>
                        <Select onValueChange={field.onChange} value={field.value ?? ""}>
                          <FormControl>
                            <SelectTrigger className={CONTROL}>
                              <SelectValue placeholder="Select a level" />
                            </SelectTrigger>
                          </FormControl>
                          <SelectContent>
                            <SelectItem value="bachelor">Bachelor’s</SelectItem>
                            <SelectItem value="master">Master’s</SelectItem>
                            <SelectItem value="phd">PhD</SelectItem>
                            <SelectItem value="postdoc">Postdoc</SelectItem>
                          </SelectContent>
                        </Select>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="gpa_4"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>GPA (4.0 scale)</FormLabel>
                        <FormDescription>
                          {form.watch("gpa_source") === "ocr"
                            ? "Read from your document — correct it if wrong"
                            : "Leave blank if unsure — we won’t filter on it"}
                        </FormDescription>
                        <FormControl>
                          <motion.div {...fieldMotion("gpa_4")} className="rounded-sc">
                            <Input
                              {...field}
                              value={field.value ?? ""}
                              onChange={(e) => {
                                field.onChange(e);
                                // A hand-edit makes this the student's own
                                // claim, which the matcher treats as exact.
                                form.setValue("gpa_source", "user");
                              }}
                              type="number"
                              step="0.01"
                              min="0"
                              max="4"
                              inputMode="decimal"
                              className={CONTROL}
                            />
                          </motion.div>
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="graduation_year"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Graduation year</FormLabel>
                        <FormDescription>Expected is fine</FormDescription>
                        <FormControl>
                          <motion.div {...fieldMotion("graduation_year")} className="rounded-sc">
                            <Input {...field} value={field.value ?? ""} type="number" inputMode="numeric" className={CONTROL} />
                          </motion.div>
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="ielts"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>IELTS score</FormLabel>
                        <FormDescription>Blank is fine — shown as “needs a test score”</FormDescription>
                        <FormControl>
                          <Input {...field} value={field.value ?? ""} type="number" step="0.5" min="0" max="9" inputMode="decimal" className={CONTROL} />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="age"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Age</FormLabel>
                        <FormDescription>Some awards have an age cap</FormDescription>
                        <FormControl>
                          <Input {...field} value={field.value ?? ""} type="number" inputMode="numeric" className={CONTROL} />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="funding_preference"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Funding needed</FormLabel>
                        <FormDescription>“Any” includes partial and tuition-only</FormDescription>
                        <Select onValueChange={field.onChange} value={field.value ?? "full"}>
                          <FormControl>
                            <SelectTrigger className={CONTROL}>
                              <SelectValue />
                            </SelectTrigger>
                          </FormControl>
                          <SelectContent>
                            <SelectItem value="full">Full funding</SelectItem>
                            <SelectItem value="any">Any funding</SelectItem>
                          </SelectContent>
                        </Select>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </div>

                {/* Fields of study */}
                {/* A checkbox group is not a single control, so it gets a real
                    fieldset/legend rather than a <label> pointing at nothing. */}
                <fieldset className="grid gap-2">
                  <legend className="text-sm leading-none font-bold">
                    Fields of study
                  </legend>
                  <p id="fields-help" className="text-sm text-muted-foreground">
                    Pick any that apply. None selected means we won’t filter by subject.
                  </p>
                  <motion.div
                    {...fieldMotion("fields_of_study")}
                    className="flex flex-wrap gap-x-5 gap-y-1 rounded-sc"
                    aria-describedby="fields-help"
                  >
                        {FIELD_TAGS.map((tag) => {
                          const checked = selectedFields.includes(tag);
                          return (
                            <label
                              key={tag}
                              className="flex min-h-11 cursor-pointer items-center gap-2 text-sm"
                            >
                              <input
                                type="checkbox"
                                className="size-4 cursor-pointer accent-[var(--fr-accent-blue)]"
                                checked={checked}
                                onChange={(e) => {
                                  const next = e.target.checked
                                    ? [...selectedFields, tag]
                                    : selectedFields.filter((f) => f !== tag);
                                  form.setValue("fields_of_study", next, {
                                    shouldDirty: true,
                                  });
                                }}
                              />
                              <span>{fieldLabel(tag)}</span>
                            </label>
                          );
                        })}
                  </motion.div>
                </fieldset>

                {/* Skills — editable chips */}
                <FormItem>
                  <Label className="font-bold" htmlFor="skill-input">
                    Skills
                  </Label>
                  <FormDescription>
                    Used to judge fit, never eligibility. Remove anything that isn’t yours.
                  </FormDescription>
                  <motion.ul layout={!reduced} className="flex flex-wrap gap-2">
                    <AnimatePresence initial={false}>
                      {skills.map((skill) => (
                        <motion.li
                          key={skill}
                          layout={!reduced}
                          initial={reduced ? false : { opacity: 0, scale: 0.9 }}
                          animate={{ opacity: 1, scale: 1 }}
                          exit={{ opacity: 0, scale: 0.9 }}
                          transition={SPRING}
                        >
                          <Badge variant="secondary" className="gap-1 py-1 pr-1 pl-2.5">
                            {skill}
                            <button
                              type="button"
                              aria-label={`Remove ${skill}`}
                              onClick={() =>
                                form.setValue(
                                  "skills",
                                  skills.filter((s) => s !== skill),
                                  { shouldDirty: true },
                                )
                              }
                              className="grid size-5 cursor-pointer place-items-center rounded-full hover:bg-foreground/10"
                            >
                              <span aria-hidden="true">×</span>
                            </button>
                          </Badge>
                        </motion.li>
                      ))}
                    </AnimatePresence>
                  </motion.ul>
                  <div className="mt-2 flex gap-2">
                    <Input
                      id="skill-input"
                      ref={skillInputRef}
                      className={CONTROL}
                      placeholder="Add a skill"
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          // Enter inside a sub-input must not submit the form.
                          e.preventDefault();
                          addSkill();
                        }
                      }}
                    />
                    <Button type="button" variant="outline" className={CONTROL} onClick={addSkill}>
                      Add
                    </Button>
                  </div>
                </FormItem>

                {/* Experience — editable rows */}
                {experience.length > 0 && (
                  <FormItem>
                    <Label className="font-bold">Experience</Label>
                    <FormDescription>
                      Pulled from your document. Fix any role or employer we misread.
                    </FormDescription>
                    <motion.ul layout={!reduced} className="flex flex-col gap-3">
                      <AnimatePresence initial={false}>
                        {experience.map((row, index) => (
                          <motion.li
                            key={row.id}
                            layout={!reduced}
                            initial={reduced ? false : { opacity: 0, y: 8 }}
                            animate={{ opacity: 1, y: 0 }}
                            exit={{ opacity: 0, height: 0 }}
                            transition={SPRING}
                            className="fr-tile grid gap-sm sm:grid-cols-[1fr_1fr_auto]"
                          >
                            <div className="grid gap-1">
                              <Label htmlFor={`exp-role-${index}`} className="text-xs text-muted-foreground">
                                Role
                              </Label>
                              <Input
                                id={`exp-role-${index}`}
                                className={CONTROL}
                                {...form.register(`experience.${index}.role` as const)}
                              />
                            </div>
                            <div className="grid gap-1">
                              <Label htmlFor={`exp-org-${index}`} className="text-xs text-muted-foreground">
                                Organisation
                              </Label>
                              <Input
                                id={`exp-org-${index}`}
                                className={CONTROL}
                                {...form.register(`experience.${index}.organisation` as const)}
                              />
                            </div>
                            <Button
                              type="button"
                              variant="ghost"
                              className={`${CONTROL} self-end`}
                              onClick={() => removeExperience(index)}
                            >
                              Remove
                              <span className="sr-only">
                                {" "}
                                {row.role || "this role"}
                              </span>
                            </Button>
                          </motion.li>
                        ))}
                      </AnimatePresence>
                    </motion.ul>
                  </FormItem>
                )}

                {submitError && (
                  <p role="alert" className="fr-body-sm rounded-md border border-destructive p-md text-destructive">
                    {submitError}
                  </p>
                )}

                <Button
                  type="submit"
                  disabled={form.formState.isSubmitting}
                  className="min-h-12 w-full font-bold sm:w-auto sm:self-start"
                >
                  {form.formState.isSubmitting ? "Finding matches…" : "See my matches →"}
                </Button>
              </form>
            </Form>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
