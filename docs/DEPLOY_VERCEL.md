# GitHub, Supabase Auth, and Vercel

The production layout is:

- Vercel hosts `frontend/`.
- Supabase provides email/password, recovery email, Google OAuth, and sessions.
- A persistent Python host such as Railway, Render, Fly.io, or a VPS hosts `backend/`.

The FastAPI backend uses SQLite files and background market-data services, so it should not be moved into a stateless Vercel function.

## 1. Protect secrets before GitHub

Commit `.env.example` files only. Do not commit a real OANDA token, Supabase service-role key, Google client secret, SQLite database, or `provider_settings.json`.

The frontend may receive the Supabase publishable/anon key. It must never receive a Supabase service-role key.

## 2. Create Supabase authentication

1. Create a Supabase project.
2. Copy the Project URL and publishable key from the project API settings.
3. In Authentication > URL Configuration, set the production Site URL to `https://YOUR-APP.vercel.app`.
4. Add redirect URLs for `http://localhost:5173/**`, the production Vercel URL, and the required Vercel preview wildcard.
5. Keep email/password and email confirmation enabled.
6. Set the email OTP length to 6 and expiry to 3600 seconds or less.

## 3. Configure confirmation-code emails

The app verifies a 6-digit email code for both registration and password recovery. In Supabase Authentication > Email Templates:

1. Customize the Confirm signup template and include `{{ .Token }}` as the visible confirmation code.
2. Customize the Reset password template and include `{{ .Token }}` as the visible recovery code.
3. Use the SH Market Analyzer name, a short expiry warning, and a message telling users never to share the code.
4. Configure a production custom SMTP provider. The default Supabase mail service is intended only for limited testing.

SMTP credentials and email-provider secrets belong in Supabase, never in the frontend or GitHub.

## 4. Enable Google sign-in

1. Create a Web OAuth client in Google Cloud.
2. Add localhost and the production Vercel domain as authorized JavaScript origins.
3. Add Supabase's callback URL as the authorized redirect URI: `https://YOUR-PROJECT-REF.supabase.co/auth/v1/callback`.
4. Put the Google Client ID and Client Secret in Supabase Authentication > Providers > Google.

The Google Client Secret belongs in Supabase only, never in this repository or Vercel frontend variables.

A Google API key is not used for account sign-in. Google sign-in requires a Web OAuth Client ID and Client Secret. Rotate any credential that has been pasted into chat, screenshots, logs, or a public repository.

## 5. Deploy the backend

Configure these server-side variables on the Python host:

```dotenv
AUTH_REQUIRED=true
SUPABASE_URL=https://YOUR-PROJECT-REF.supabase.co
SUPABASE_PUBLISHABLE_KEY=sb_publishable_REPLACE_ME
CORS_ORIGINS=https://YOUR-APP.vercel.app
```

For local testing, copy `backend/.env.example` to `backend/.env` and replace the example values. Real hosting variables override values from the local file.

Deploy the backend with a persistent disk for `backend/data/`. Confirm that `https://YOUR-API/api/health` returns `authentication.required: true` and `authentication.configured: true`.

Assign `app_metadata.role = admin` only to trusted owner accounts using a trusted Supabase admin surface. Regular users remain `user` and cannot access provider credentials, diagnostics, test-data controls, or destructive market-data actions. Never use editable `user_metadata` for authorization.

## 6. Deploy the frontend on Vercel

1. Import the GitHub repository into Vercel.
2. Set Root Directory to `frontend` and Framework Preset to Vite.
3. Add the following Production and Preview variables:

```dotenv
VITE_API_BASE_URL=https://YOUR-API
VITE_SUPABASE_URL=https://YOUR-PROJECT-REF.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=sb_publishable_REPLACE_ME
VITE_AUTH_REQUIRED=true
```

4. Redeploy after every environment-variable change.

## 7. Release check

- Register with email and confirm the 6-digit code.
- Sign in, refresh the browser, and confirm the session remains active.
- Sign out and sign back in with Google.
- Request a password reset, confirm the 6-digit recovery code, and choose a new password.
- Confirm protected API calls return `401` without a token and work after sign-in.
- Check desktop and mobile layouts on the production URL.
