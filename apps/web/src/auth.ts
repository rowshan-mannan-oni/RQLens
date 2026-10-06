import NextAuth from "next-auth";
import GitHub from "next-auth/providers/github";
import Google from "next-auth/providers/google";

// A provider is enabled when its client ID is set in .env.
const google = Boolean(process.env.AUTH_GOOGLE_ID);
const github = Boolean(process.env.AUTH_GITHUB_ID);

export const signInOptions = [
  ...(google ? [{ id: "google", name: "Google" }] : []),
  ...(github ? [{ id: "github", name: "GitHub" }] : []),
];

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [...(google ? [Google] : []), ...(github ? [GitHub] : [])],
  pages: { signIn: "/" },
});
