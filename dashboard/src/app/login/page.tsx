import { LoginForm } from "@/components/login-form";
import { login } from "@/lib/auth-actions";

export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  const { expired } = await searchParams;
  const notice =
    expired === "1"
      ? "Your session has ended: the admin key was refused. Sign in again."
      : undefined;

  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="mb-1 text-lg font-semibold">LLM Gateway admin</h1>
        <p className="mb-6 text-sm text-slate-600">
          Sign in with an admin key. Create one with{" "}
          <code className="font-mono text-xs">
            python -m app.admin create-admin-key --name you
          </code>
          .
        </p>
        <LoginForm action={login} notice={notice} />
      </div>
    </main>
  );
}
