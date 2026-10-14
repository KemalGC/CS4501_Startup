# Startup 1: CloudGuard — Verified Terraform Security Fixes

**Inspiration from YC Startup Directory:** [ZeroPath (YC Summer 2024)](https://www.ycombinator.com/companies/zeropath), which identifies, verifies, and fixes software vulnerabilities.

**Proposed startup (our adaptation):** CloudGuard reviews Terraform pull requests for a small set of common AWS security misconfigurations, proposes fixes, and releases a patch only if independent tooling confirms it is valid and the specific violation is resolved. CloudGuard is an original *scoped product concept inspired by* ZeroPath, not a description of an existing ZeroPath feature.

## How this idea meets all eight criteria

### 1. Solves one problem extremely well
Student developers and small teams can accidentally commit insecure infrastructure-as-code. CloudGuard addresses **one precise problem: fixing unsafe Terraform configuration changes before merge**. The initial MVP supports only three concrete policies: publicly accessible S3 buckets, overly permissive security-group inbound rules, and wildcard IAM actions/resources. It does not try to be a full penetration tester or cloud management platform.

### 2. I know or can access target customers
Initial users are classmates building AWS applications, student engineering projects, and campus software teams. I can ask these developers to review a prototype and provide **consented demo Terraform repositories**, then interview small startup development teams. I would validate access and demand through interviews rather than assuming paying customers already exist.

### 3. Familiar with the infrastructure
I have worked with AWS, Terraform, VPCs, IAM, security groups, and container deployments. The MVP adds GitHub webhooks (or an uploaded ZIP), Python/FastAPI, an LLM API, Terraform CLI, and Checkov. These technologies are within reach or straightforward to learn.

### 4. Significantly reimagines the problem
Typical scanners produce warning lists for developers to decipher. CloudGuard turns static findings into **policy-constrained, verified proposed repairs** that can be inspected as diffs. It is deliberately infrastructure-specific, rather than a general-purpose AI coding assistant, and minimizes manual security triage for tiny engineering teams.

### 5. An LLM/generative model is core
The LLM reads the Terraform resource, surrounding configuration, and violation explanation, then **generates a targeted Terraform patch**. A deterministic scanner alone can detect a bad resource but cannot reliably construct a context-aware corrected configuration while preserving the developer's intended architecture.

### 6. Validation guardrail: no unvalidated LLM artifact reaches users
Each generated patch is quarantined in a temporary workspace. A Python controller runs:
- `terraform fmt -check` and `terraform init -backend=false` / `terraform validate`;
- Checkov on the affected Terraform files, including the originally triggered policy;
- a structured diff validator allowing changes only to approved files/resources and rejecting new dangerous permissions.

Only after all checks pass is the proposed diff or PR draft released. A failed run may show a **non-generative status** ("Unable to produce a verified fix"), but no failing patch is presented as a solution. Terraform validation and policy checks are meaningful guardrails, not proof that every cloud risk has been eliminated.

### 7. Automatic self-correction loop
When a check fails, the controller passes the **exact scanner finding, stderr, failed rule ID, and current candidate diff** back to the LLM. It asks for a revised patch, runs all validators again, and repeats for at most three attempts. Persistent failures are held for manual review; the LLM cannot waive a validator or broaden permissions just to make a check pass.

### 8. Fully deployable MVP
A Dockerized FastAPI service receives a GitHub PR event or ZIP upload, starts an isolated job container with Terraform and Checkov, calls the LLM, performs retries, and posts an approved patch. A small React page displays validated fixes and failure statuses. It can be deployed on AWS ECS Fargate or a smaller container host, with short-lived sandbox credentials and **no automatic `terraform apply`**.

## Concrete MVP demonstration
1. Submit a demo Terraform security group exposing SSH to `0.0.0.0/0`.
2. Checkov flags the policy violation.
3. The LLM produces a narrower access rule using the caller's supplied allowed CIDR.
4. Terraform syntax/configuration and policy checks run.
5. Intentionally break the first patch to show the validator error being fed back automatically; release only the subsequent passing patch.

**Validation/quality metric:** Share of suggested patches passing all validators; median retry count; share of confirmed policy violations fixed without changing unrelated resources.

**Boundaries:** No production credentials, no live attacks, and no promise that static checks establish absolute security.
