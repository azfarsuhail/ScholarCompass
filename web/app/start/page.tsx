import { ProfileForm } from "@/components/ProfileForm";
import { StepIndicator } from "@/components/StepIndicator";

// Server component wrapper: only the form itself is interactive, so the page
// shell, heading and step indicator stay out of the client bundle.
export const metadata = {
  title: "Your details — ScholarCompass",
};

export default function StartPage() {
  return (
    <main id="main" className="mx-auto w-full max-w-2xl flex-1 px-6 py-12">
      <StepIndicator current={0} />

      <div className="mb-8">
        <h1 className="text-3xl font-bold text-balance">
          Tell us enough to filter, no more
        </h1>
        <p className="mt-2 text-muted-foreground">
          Every field is optional. Blank means “don’t filter on this” — we never
          guess a value you didn’t give us.
        </p>
      </div>

      <ProfileForm />
    </main>
  );
}
