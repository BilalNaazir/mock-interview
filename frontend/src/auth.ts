// auth.ts - Login settings and helpers.
//
// We use OpenID Connect (OIDC), the standard behind "Sign in with ...".
// The react-oidc-context library does the heavy lifting:
//   1. signinRedirect() sends the user to Cognito's hosted login page.
//   2. After login, Cognito redirects back here with a one-time "code".
//   3. The library swaps that code for tokens (the PKCE "code flow", the
//      recommended secure flow for browser apps), stores them, and keeps
//      them fresh.

import type { AuthProviderProps } from "react-oidc-context";
import type { User } from "oidc-client-ts";
import { config } from "./config";

const { region, userPoolId, clientId, domain } = config.cognito;

// Remember where the user was trying to go before being sent to log in.
export interface LoginState {
  returnTo: string;
}

export const oidcConfig: AuthProviderProps = {
  // "authority" is the login server. For Cognito, it's the user pool's address.
  authority: `https://cognito-idp.${region}.amazonaws.com/${userPoolId}`,
  client_id: clientId,
  // Where Cognito sends the user back to. Must EXACTLY match a callback URL
  // configured in the Cognito app client, or Cognito shows an error.
  redirect_uri: `${window.location.origin}/`,
  response_type: "code",
  // openid = log in, email + profile = let us read their email and name.
  scope: "openid email profile",

  // Runs once after returning from Cognito. We remove the ?code=... from
  // the address bar and take the user to the page they originally wanted.
  onSigninCallback: (user: User | void) => {
    const returnTo = (user?.state as LoginState | undefined)?.returnTo ?? "/";
    window.history.replaceState({}, document.title, returnTo);
    // Tell React Router the address changed, so it shows the right page.
    window.dispatchEvent(new PopStateEvent("popstate"));
  },
};

// Logging out has two parts: forget the tokens in this browser, AND end the
// session on Cognito's side. Without the second part, clicking "log in"
// again would instantly log the same person back in without asking.
export function cognitoLogoutUrl(): string {
  const logoutUri = `${window.location.origin}/`;
  return `${domain}/logout?client_id=${clientId}&logout_uri=${encodeURIComponent(logoutUri)}`;
}
