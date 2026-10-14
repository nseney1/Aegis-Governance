---
id: destructive-ops
domain: security
non_standard: true
name: Destructive Ops Safety
description: Mandates dry-runs and explicit user confirmation for destructive state mutations across infrastructure, databases, and filesystem/git.
trigger: model_decision
enforcement: advisory
---
# State-Mutating Operations Safety Net

> **Role**: This rule acts as a safety boundary for destructive or state-mutating operations to prevent accidental data loss, cloud spend, or unintentional resource mutations.

## 1. Dry-Run Mandate
- **No Blind Applies**: Never automatically execute commands that mutate state without explicit permission. This includes:
  1. **Cloud Infrastructure**: `terraform apply`, `kubectl apply`, `aws cloudformation deploy`
  2. **Database Mutations**: `DROP TABLE`, `prisma migrate reset`, destructive migrations
  3. **Filesystem/Git**: `rm -rf`, `git reset --hard`, `git push --force`, recursive deletes
  4. **Bulk VCS Staging**: `git add -A`, `git add .` — always run `git status` or `git add -n` (dry-run) first to verify file count and total size. Audit `.gitignore` before the first commit of any project.
- **Mandatory Plans**: Always run the dry-run equivalent first (e.g., `terraform plan`, `kubectl diff`, `git diff`) and present the output. Explicitly pause and require the user's sign-off before proceeding.

## 2. Cost-Warning System
- **Flag Persistent Costs**: Before applying any infrastructure change, explicitly flag if the change introduces a persistently running resource (e.g., an EC2 instance, an RDS instance, a NAT Gateway, or an un-capped load balancer).
- **Surprise Prevention**: Ensure the user is fully aware of the monthly idle cost implications of the resources being stood up.
