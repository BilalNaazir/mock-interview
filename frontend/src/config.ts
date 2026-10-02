// config.ts - Reads the VITE_ settings from .env.local (or, in staging and
// prod, from values GitHub Actions provides at build time).
//
// Doing it in ONE place means a missing setting produces one clear error,
// instead of confusing failures scattered around the app.

function required(name: string): string {
  const value = import.meta.env[name];
  if (!value) {
    throw new Error(`Missing setting ${name}. Did you create frontend/.env.local from .env.example?`);
  }
  return value;
}

export const config = {
  apiUrl: required("VITE_API_URL"),
  cognito: {
    region: required("VITE_COGNITO_REGION"),
    userPoolId: required("VITE_COGNITO_USER_POOL_ID"),
    clientId: required("VITE_COGNITO_CLIENT_ID"),
    domain: required("VITE_COGNITO_DOMAIN"),
  },
};
