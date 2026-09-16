# k3s deployment

This directory is the shared deployment entry point for on-premises and AWS
EC2 k3s clusters. The same `teoria` chart is used in both environments; only
environment values differ.

```text
k3s/
├── charts/teoria/       Teoria-owned application workloads
├── values/on-prem.yaml  On-premises overrides
├── values/aws-ec2.yaml  AWS EC2 overrides
└── helmfile.yaml.gotmpl Environment selection and release composition
```

The chart is currently a scaffold and intentionally contains no workload
templates. Existing Docker Compose deployment remains the local development
entry point.

## Deployment boundary

- EC2 hosts the k3s cluster.
- Application images are built in CI, pushed to ECR, and pulled by k3s.
- Bid-document objects use S3 or another externally managed S3-compatible
  store.
- PostgreSQL connection URLs and all credentials are provided through
  pre-created Kubernetes Secrets. Secrets must not be committed in values.
- PostgreSQL, Prefect, Redis, certificate management, and monitoring should be
  composed as upstream Helm releases or managed externally instead of copied
  into the Teoria chart.

Expected Secret names are declared in `charts/teoria/values.yaml`:

- `teoria-pipeline-database`
- `teoria-runtime-database`
- `teoria-object-storage`
- `teoria-runtime`
- `teoria-prefect`

Render the selected environment after workload templates are added:

```bash
helmfile -f deploy/k3s/helmfile.yaml.gotmpl -e on-prem template
helmfile -f deploy/k3s/helmfile.yaml.gotmpl -e aws-ec2 template
```

CI pins the combined Helm/Helmfile tool image to
`ghcr.io/helmfile/helmfile:v1.7.1` and renders both environments on every
change.

AWS infrastructure code should be added under `deploy/aws/terraform/` only
when the EC2, network, IAM, ECR, and related infrastructure contracts are
defined.
