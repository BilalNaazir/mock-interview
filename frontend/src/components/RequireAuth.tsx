// RequireAuth.tsx - Wrap any page in <RequireAuth> to make it login-only.
//
// Note: this only improves the EXPERIENCE (sending people to log in). The
// real protection is on the backend, which rejects requests without a valid
// token. Never rely on the frontend alone for security - users can change
// any code running in their own browser.
import { useEffect, type ReactNode } from "react";
import { useAuth } from "react-oidc-context";
import { useLocation } from "react-router";
import type { LoginState } from "../auth";

export default function RequireAuth({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const location = useLocation();
  const needsLogin = !auth.isLoading && !auth.isAuthenticated && !auth.error;

  useEffect(() => {
    if (needsLogin) {
      // Remember this page so we can come back after logging in (see auth.ts).
      const state: LoginState = { returnTo: location.pathname };
      auth.signinRedirect({ state });
    }
  }, [needsLogin, auth, location.pathname]);

  if (auth.error) {
    return <p className="error">Login problem: {auth.error.message}</p>;
  }
  if (!auth.isAuthenticated) {
    return <p className="muted">Taking you to log in...</p>;
  }
  return <>{children}</>;
}
