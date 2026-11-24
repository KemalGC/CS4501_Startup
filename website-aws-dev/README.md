# StrokeSense AWS development website

This is an **isolated copy** of the published StrokeSense design for the
`aws-dev` branch. It does not embed the live Render bridge or send files to the
production website. Its analyzer shows an honest, local-only preview until
Cognito and the AWS HTTP API are deployed and configured. When real CPU
analysis completes, it displays the self-contained HTML technique report
from private S3 JSON inside a restricted sandboxed iframe, with a separate
report download link.
On successful analysis the browser also requests an HTML download automatically,
with the visible download button as a fallback. If the report preview cannot be
fetched (for example because of a browser CORS restriction), the button offers
the signed raw JSON report until that short-lived URL expires.
The browser displays a horizontally scrollable, rower-by-rower frame gallery
using owner-scoped, signed S3 artifact URLs from `/reports/{job_id}/artifacts`
when available. For older reports it can display only bounded embedded PNG,
JPEG or WebP screenshots from the already downloaded report HTML; no report
HTML is inserted into the page outside the restricted report iframe. The
annotated video player is shown only when the backend provides an actual
private, signed MP4/WebM URL; legacy reports display an unavailable message.

The uploader includes an unchecked, optional **administrator review** consent.
The `allow_admin_review` boolean is sent with `POST /uploads/start` and defaults
to false. Videos and reports are private by default; checking the box explicitly
allows an administrator to review that upload and analysis.

## Run locally

```bash
cd website-aws-dev
npm run test
npm run build
python -m http.server 8000 --directory dist
```

Open `http://localhost:8000/demos/` to test tier selection, file validation,
the planned Google sign-in workflow, and the no-backend state. Browser-based
Google login requires an **HTTPS deployment** and a configured Cognito client;
it will not work using the default blank configuration.

The public `/feedback/` page replaces the private feedback-study invitation.
Visitors can rate website usability from **1–5** and optionally leave a comment
(up to 1,000 characters), without signing in. The form sends JSON directly to
the AWS API. If the API isn't configured, submission is unavailable rather
than silently discarding responses. Old `/study/` links redirect to `/feedback/`.

The `/library/` page is a **private My Analyses history** for the signed-in
Google account. It requests only owner-scoped history from the AWS API using
the Cognito access token in this tab's session storage. Entries show file name,
submission status, clip/analysis duration, dates and report availability, with
links back to `/demos/?job=<id>` to resume or download an available report.
Completed cards also offer **Watch annotated video** while the report is
available. The owner-authenticated `/reports/{id}/artifacts` request returns
a very short-lived signed S3 URL only when the annotated MP4 was published.
The browser checks its signature and exact dev bucket, then places it in a
native video player; no raw upload is substituted when annotated media is
missing or expired.
No video is permanently archived: original uploads are short-lived (currently
about 1 day), reports expire separately (currently 3 days), and the retained
history metadata also expires on its own schedule (currently about 10 days).
Until the backend owner-scoped history route is deployed, the page shows a
one-time rollout notice for HTTP 404 rather than retrying in a loop.
If an owner has voluntarily permitted staff video review for a particular
job, their history card offers **Revoke staff access**. This sends the
owner-authenticated `POST /analysis/jobs/{id}/review` request with
`{"allow_admin_review":false}`. Revocation prevents new staff playback
authorization; existing video links may remain valid for up to 60 seconds,
and it cannot undo a copy already obtained.

The unlinked `/admin/` page is for separately authorized StrokeSense staff.
It lists **only owner-opted-in jobs** through `GET /admin/jobs`, shows analysis
wall time and other returned timing metrics, and requests a single temporary
video URL only after a staff member clicks a review button. Playback prefers
an annotated result when available, otherwise an original upload still within
retention. The AWS backend must verify both admin allowlisting and current
owner consent on every request; the static page's URL is not an access control.
The signed S3 playback URL lasts no longer than about 60 seconds and is not
printed in messages or persisted. No public navigation advertises `/admin/`.

## Separate Vercel project

- Project: `strokesense-aws-dev` (separate from `strokesense-review`)
- Repository: `KemalGC/CS4501_Startup`
- Root directory: `website-aws-dev`
- Branch to test: `aws-dev`
- Framework: Other / static
- Build command: `npm run build`
- Output directory: `dist`

Set the following environment variables **on the AWS development Vercel
project only**, using Preview scope for branch previews. The build writes
public coordinates into `dist/assets/aws-config.js`.

| Variable | Example | Purpose |
| --- | --- | --- |
| `STROKESENSE_AWS_API_URL` | `https://example.execute-api.us-east-1.amazonaws.com` | AWS HTTP API base URL |
| `STROKESENSE_COGNITO_DOMAIN` | `https://example.auth.us-east-1.amazoncognito.com` | Cognito managed login domain |
| `STROKESENSE_COGNITO_CLIENT_ID` | Cognito **public** app client ID | Public SPA OAuth client |
| `STROKESENSE_ENABLE_CPU_ANALYSIS` | `false` | Frontend safety switch: turn on only after AWS Batch and global admission guards are live and verified |
| `STROKESENSE_ENABLE_PREMIUM_ANALYSIS` | `false` | Frontend rollout switch; server-confirmed Premium access and GPU availability are also required. Keep false during smoke-only preparation. |

`STROKESENSE_ENABLE_DEEP_ANALYSIS` remains a compatibility alias for existing
deployment settings. It does not bypass server permission or runtime checks.

Do not put Google client secrets, AWS secret keys, AWS session credentials,
Stripe API keys, or private tokens in these variables or in `NEXT_PUBLIC_*`
variables. AWS API actions are performed with Lambda's IAM execution role.

For Google sign-in, configure the Cognito app client's **allowed callback URL**
to match the actual URL of this site ending in `/demos/`; the Google OAuth
client's authorized redirect is Cognito's `/oauth2/idpresponse`, **not** the
Vercel URL. The browser uses Authorization Code + PKCE and AWS verifies JWTs
server-side. Preview branch URLs may differ between deployments, so prefer a
stable `strokesense-aws-dev.vercel.app` domain once established.

### Troubleshoot Google login

1. Test first at `https://strokesense-aws-dev.vercel.app/demos/`, not a
   temporary Vercel preview deployment. Preview deployments can require a
   separate Vercel login, and each preview hostname needs its **own** exact
   Cognito callback URL if you want to test Cognito there.
2. The Cognito app client must allow the full callback URL
   `https://strokesense-aws-dev.vercel.app/demos/`, including the trailing slash.
   The Google Cloud OAuth **Web** client must authorize Cognito's redirect URL
   `https://strokesense-dev-851226124502.auth.us-east-1.amazoncognito.com/oauth2/idpresponse`.
3. With an AWS profile authorized for read-only Cognito calls, inspect **only**
   the non-secret fields below. Do not share OAuth codes, tokens, `ProviderDetails`
   or the Google client secret:

   ```powershell
   aws cognito-idp describe-user-pool-client `
       --region us-east-1 `
       --user-pool-id us-east-1_SACxYjDH5 `
       --client-id 2tjrv7rsu77hhbk45lrg0ii83p `
       --query 'UserPoolClient.{CallbackURLs:CallbackURLs,AllowedOAuthFlows:AllowedOAuthFlows,SupportedIdentityProviders:SupportedIdentityProviders}'

   aws cognito-idp describe-identity-provider `
       --region us-east-1 `
       --user-pool-id us-east-1_SACxYjDH5 `
       --provider-name Google `
       --query 'IdentityProvider.AttributeMapping'
   ```

4. If the Google account chooser works but the return to StrokeSense fails,
   the error code and description now appear in the **Your account** panel.
   Share only that error text for troubleshooting, never a callback URL that
   contains an authorization code. Google consent-screen test-user restrictions
   can also block accounts that aren't on an approved list.

## Product limits

- Free analysis: **100 MB max per video**, **300 MB cumulative over the
  account's lifetime**; only successful processing consumes quota.
- Premium: **750 MB max per video**, access granted by an administrator.
  Access is separate from GPU availability; this preparation release keeps
  GPU analysis unavailable while hardware and job dispatch are validated.
- All sizes are decimal MB (1 MB = 1,000,000 bytes).
- Free reports: 72 hours; Premium reports: 30 days.
- Public-beta CPU analysis: **at most 5 job submissions per UTC day and
  50 per UTC month across all users**, enforced by DynamoDB transactions.
  The tested worker uses 2 vCPU and 4 GiB; 10 maximum Batch vCPUs supports
  up to five concurrent jobs only if the account's Fargate quota allows it.
- A submitted job's identifier is held in per-tab session storage so returning
  to the same tab after a refresh can resume checking its report status.
- The 750 MB upload path uses S3 presigned multipart PUT URLs. Videos never
  pass through Vercel or API Gateway request bodies.

## API contract

The client expects an authenticated AWS HTTP API:

| Route | Description |
| --- | --- |
| `GET /me` | Server-confirmed `is_admin` and `premium_access` (`granted`, `available`, `reason`, `source`, `updated_at`, `owner_protected`); no account permission is inferred from a browser-decoded email |
| `GET /admin/users?email=...` | Admin-only exact lookup of an existing verified Google/Cognito account; returns `users` with stable `user_id`, `email`, `email_verified`, and `premium_access` |
| `POST /admin/users/{user_id}/premium` | Admin-only grant/revoke with `{"enabled":true,"reason":"Approved for the Premium pilot"}`; returns the updated verified user and records an audit event |
| `POST /uploads/start` | Reserve quota; return `video_id`, `part_size_bytes`, `part_count` |
| `POST /uploads/part` | Sign the PUT for an upload part |
| `POST /uploads/complete` | Complete multipart upload using part ETags |
| `POST /uploads/abort` | Abort unsubmitted upload and release its reservation |
| `POST /analysis/jobs` | Submit a CPU or GPU analysis job |
| `GET /analysis/jobs/{job_id}` | Poll the owner's analysis status |
| `GET /analysis/jobs?limit=20&cursor=...` | Paginated owner-scoped private history; returns `jobs` and an opaque `next_cursor` (never enumerate other users) |
| `POST /analysis/jobs/{job_id}/review` | Owner revokes previously granted staff video review (`{"allow_admin_review":false}`) |
| `GET /admin/jobs?limit=20&cursor=...` | Privileged paginated list of opted-in analysis records, including timing, without owner identity |
| `GET /admin/videos/{job_id}` | Privileged per-click access to a temporary annotated-or-original video URL, requiring current owner consent |
| `GET /reports/{job_id}` | Return a short-lived private report download URL |
| `GET /reports/{job_id}/artifacts` | Owner-scoped, short-lived annotated-video playback URL and per-rower snapshot/sequence frames; may be empty for older reports |
| `POST /feedback` | Public website-usability rating (1–5) with optional comment; no video or account required |

The AWS backend must authorize ownership of every video/job and charge/release
quota atomically, including concurrent uploads, failed jobs and repeated
requests. The web client does not authorize payments or decide account eligibility.

## Premium access in the admin UI

1. The deployment operator first verifies the owner’s Google/Cognito account
   and pins its immutable Cognito subject in the backend. The owner email is
   not an allowlist shipped to the browser. See the infrastructure Premium
   preparation guide for the operator step.
2. Sign in on the analyzer with an authorized administrator account. Once
   `GET /me` confirms administrator status, **Open admin** appears in the
   account panel. The admin page is also available directly at `/admin/`.
3. In **Premium members**, enter the exact Google email of an existing user.
   A new user must sign in once before lookup can find their account.
4. Check the returned verified email and account ID. Enter one line of 3–500
   visible characters explaining the change, then choose **Grant Premium
   access** or **Revoke Premium access**. Every lookup and mutation is checked
   by the backend; hidden controls are not an authorization boundary.
5. The user can choose **Refresh account access** on the analyzer to see their
   current grant. **Premium access granted** and **GPU analysis available**
   are separate states. A grant never starts an instance or enables dispatch.

Owner access is protected from revocation in the web admin UI. Granting
Premium to another user does not make them an administrator, change their
Free Analysis allowance, or grant consent to review their videos. Consented
video review stays in its separate admin section.

The access form does not retry mutations automatically. If a response is lost,
it hides the selected target and asks the administrator to look the account up
again before another change. Identity, permission and audit failures fail
closed. A failed `/me` capability request leaves the existing Free CPU flow
usable while Premium stays unavailable.

**Compatibility:** the visible GPU tier is named **Premium**. Existing AWS
job records and uploads still use the internal `paid` tier value so the UI
remains compatible with the deployed worker image and report paths. Existing
resource names are not renamed as part of this interface change.

## Approval boundary

This branch contains infrastructure **code**, not provisioned infrastructure.
Do not run `terraform apply`, enable paid credits, launch GPU EC2 instances,
upgrade the AWS account plan, or switch the production website without explicit
owner approval. The $100 AWS promotional credit and the AWS Free Plan have
separate expiration dates; verify the Free Plan's actual remaining days before
deployment.
