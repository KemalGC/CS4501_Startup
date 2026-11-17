# StrokeSense AWS development website

This is an **isolated copy** of the published StrokeSense design for the
`aws-dev` branch. It does not embed the live Render bridge or send files to the
production website. Its analyzer shows an honest, local-only preview until
Cognito and the AWS HTTP API are deployed and configured.

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
| `STROKESENSE_ENABLE_DEEP_ANALYSIS` | `false` | Must remain false until payment and GPU testing are approved |

Do not put Google client secrets, AWS secret keys, AWS session credentials,
Stripe API keys, or private tokens in these variables or in `NEXT_PUBLIC_*`
variables. AWS API actions are performed with Lambda's IAM execution role.

For Google sign-in, configure the Cognito app client's **allowed callback URL**
to match the actual URL of this site ending in `/demos/`; the Google OAuth
client's authorized redirect is Cognito's `/oauth2/idpresponse`, **not** the
Vercel URL. The browser uses Authorization Code + PKCE and AWS verifies JWTs
server-side. Preview branch URLs may differ between deployments, so prefer a
stable `strokesense-aws-dev.vercel.app` domain once established.

## Product limits

- Free analysis: **100 MB max per video**, **300 MB cumulative over the
  account's lifetime**; only successful processing consumes quota.
- Deep Analysis: **750 MB max per video**, paid credits required, GPU feature
  disabled until separately approved.
- All sizes are decimal MB (1 MB = 1,000,000 bytes).
- Free reports: 72 hours; Deep Analysis reports: 30 days.
- The 750 MB upload path uses S3 presigned multipart PUT URLs. Videos never
  pass through Vercel or API Gateway request bodies.

## API contract

The client expects an authenticated AWS HTTP API:

| Route | Description |
| --- | --- |
| `POST /uploads/start` | Reserve quota; return `video_id`, `part_size_bytes`, `part_count` |
| `POST /uploads/part` | Sign the PUT for an upload part |
| `POST /uploads/complete` | Complete multipart upload using part ETags |
| `POST /uploads/abort` | Abort unsubmitted upload and release its reservation |
| `POST /analysis/jobs` | Submit a CPU or GPU analysis job |
| `GET /analysis/jobs/{job_id}` | Poll the owner's analysis status |
| `GET /reports/{job_id}` | Return a short-lived private report download URL |

The AWS backend must authorize ownership of every video/job and charge/release
quota atomically, including concurrent uploads, failed jobs and repeated
requests. The web client does not create paid credits, authorize payments, or
decide account eligibility.

## Approval boundary

This branch contains infrastructure **code**, not provisioned infrastructure.
Do not run `terraform apply`, enable paid credits, launch GPU EC2 instances,
upgrade the AWS account plan, or switch the production website without explicit
owner approval. The $100 AWS promotional credit and the AWS Free Plan have
separate expiration dates; verify the Free Plan's actual remaining days before
deployment.
