import NextAuth from "next-auth";
import Google from "next-auth/providers/google";

/**
 * Google sign-in, open to any Google account.
 *
 * Signing in is NOT permission. It only establishes who somebody is; whether
 * they can see a tree is decided by the `members` table, checked server-side on
 * every page and every action. That is deliberate — a clinician at Sangath may
 * be on any mail provider, and restricting by domain would keep the wrong
 * people out and let the wrong people in.
 */
export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [Google],
  pages: { signIn: "/signin" },
  callbacks: {
    async session({ session, token }) {
      if (session.user && token.email) session.user.email = token.email;
      return session;
    },
  },
});
