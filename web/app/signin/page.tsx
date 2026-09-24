import { redirect } from "next/navigation";
import { auth, signIn } from "@/auth";

/**
 * The sign-in page.
 *
 * One button, because there is only one honest choice to make here. Note what
 * it does NOT say: it does not ask for an organisation. Signing in establishes
 * who you are; which trees you can open is decided afterwards, server-side,
 * from the members table.
 */
export default async function SignIn({
  searchParams,
}: {
  searchParams: Promise<{ callbackUrl?: string }>;
}) {
  const session = await auth();
  if (session?.user?.email) redirect("/");
  const { callbackUrl } = await searchParams;

  return (
    <main className="min-h-screen grid place-items-center px-6 py-16">
      <div className="w-full max-w-[420px]">
        <div className="mb-8 text-center">
          <div className="text-4xl mb-3">🧠</div>
          <h1 className="text-[22px] font-semibold tracking-tight">
            RDR Clinical Knowledge Base
          </h1>
          <p className="note mt-2">
            A knowledge base your team builds by correcting it. Every rule is
            readable, and every rule can be corrected.
          </p>
        </div>

        <div className="surface p-7">
          <form
            action={async () => {
              "use server";
              await signIn("google", { redirectTo: callbackUrl || "/" });
            }}
          >
            <button
              type="submit"
              className="btn-base w-full flex items-center justify-center gap-3 !py-3 font-medium"
            >
              <GoogleMark />
              Continue with Google
            </button>
          </form>

          <p className="note mt-5 text-center">
            Any Google account can sign in. You will see a knowledge base only
            if someone has added your email to an organisation.
          </p>
        </div>

        <p className="note mt-6 text-center">
          Not been added yet? Ask whoever runs your organisation to add the
          address you are signing in with.
        </p>
      </div>
    </main>
  );
}

function GoogleMark() {
  return (
    <svg width="17" height="17" viewBox="0 0 48 48" aria-hidden="true">
      <path
        fill="#FFC107"
        d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.3 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.9 1.2 8 3.1l5.7-5.7C34.0 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z"
      />
      <path
        fill="#FF3D00"
        d="M6.3 14.7l6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.9 1.2 8 3.1l5.7-5.7C34.0 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"
      />
      <path
        fill="#4CAF50"
        d="M24 44c5.2 0 9.8-2 13.3-5.2l-6.2-5.2C29.1 35.1 26.7 36 24 36c-5.3 0-9.7-3.3-11.3-8l-6.5 5C9.6 39.6 16.2 44 24 44z"
      />
      <path
        fill="#1976D2"
        d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.1-4.1 5.5l6.2 5.2C39.1 36.7 44 31.1 44 24c0-1.3-.1-2.4-.4-3.5z"
      />
    </svg>
  );
}
