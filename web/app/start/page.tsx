import { ProfileForm } from "@/components/ProfileForm";
import { StepIndicator } from "@/components/StepIndicator";

// Server component wrapper: only the form itself is interactive, so the page
// shell, heading and step indicator stay out of the client bundle.
export const metadata = {
  title: "Your details — ScholarCompass",
};

export default function StartPage() {
  return (
    <main id="main" className="mx-auto w-full max-w-[760px] flex-1 px-lg py-xxl sm:px-xl">
      <StepIndicator current={0} />

      <div className="mb-xl">
        <h1 className="fr-display-lg text-ink">
          Tell us enough to filter, no more
        </h1>
        <p className="fr-body-lg mt-sm text-ink-muted">
          Every field is optional. Blank means “don’t filter on this” — we never
          guess a value you didn’t give us.
        </p>
      </div>

      <ProfileForm />
    </main>
  );
}
