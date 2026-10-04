// Header.tsx - The bar at the top: app name, and login/logout controls.
import { useAuth } from "react-oidc-context";
import { Link } from "react-router";
import { useApi } from "../api";
import { cognitoLogoutUrl } from "../auth";
import type { UserProfile } from "../types";

export default function Header() {
  const auth = useAuth();
  const token = auth.user?.access_token;

  // Only ask the backend for the profile once we're logged in (null = skip).
  const { data: profile } = useApi<UserProfile>(auth.isAuthenticated ? "/users/me" : null, token);

  async function logOut() {
    await auth.removeUser();                 // forget tokens in this browser
    window.location.href = cognitoLogoutUrl(); // end the session at Cognito too
  }

  return (
    <header className="header">
      <Link to="/" className="brand">
        Mock Interview
      </Link>

      <div className="header-actions">
        {auth.isLoading ? (
          <span className="muted">Checking login...</span>
        ) : auth.isAuthenticated ? (
          <>
            <Link to="/my-interviews">My interviews</Link>
            <span className="muted">Hi, {profile?.name ?? "there"}</span>
            <button className="button secondary" onClick={logOut}>
              Log out
            </button>
          </>
        ) : (
          <>
            {/* Cognito's hosted page offers log in AND "Sign up" (register). */}
            <button className="button secondary" onClick={() => auth.signinRedirect()}>
              Log in / Register
            </button>
            {/* identity_provider=Google skips Cognito's page and goes straight to Google. */}
            <button
              className="button"
              onClick={() => auth.signinRedirect({ extraQueryParams: { identity_provider: "Google" } })}
            >
              Continue with Google
            </button>
          </>
        )}
      </div>
    </header>
  );
}
