# Org Reusable Workflows

This repository contains a collection of reusable GitHub Actions workflows designed to streamline and standardize CI/CD processes across our organization.

## Quick Start: Wire Up a New Microservice Repo

If your new repo lives in one of the 4 trusted orgs (commercesong, enterprisevibecoding, elevatorfunrooms, forgotpw), the GitHub-side setup is **already done for you** — org secrets and OIDC trust both cover any repo in those orgs automatically. The only per-repo work is:

1. **Add a `terraform/` directory** following the [standard module structure](https://github.com/commercesong/infrastructure/blob/main/README.md#module-structure): `provider.tf` (empty `backend "s3" {}`), `main.tf`, `variables.tf`, `outputs.tf`, `env-dev.tfvars`, `env-prod.tfvars`, and a `TF_KEY` file containing a unique state key (e.g., `my-service`).

2. **Add a workflow** at `.github/workflows/<name>.yml` calling one of the reusable workflows (see examples below). For pure-infrastructure modules use `terraform-infrastructure.yml`; for containerized services use `cicd-terraform-container.yml`.

3. **Push.** Workflow triggers on pushes to `main`/`develop` and PRs (per the trigger patterns in the reusable workflows).

That's it — no GitHub UI configuration, no secret-setting, no IAM changes. If your new repo is in a **brand-new org** (not one of the 4 above), see the "Adding a new GitHub org" sections in [`commercesong/infrastructure/README.md`](https://github.com/commercesong/infrastructure/blob/main/README.md) and [`infrastructure/github-oidc/README.md`](https://github.com/commercesong/infrastructure/blob/main/github-oidc/README.md) — both must be updated together.

## Workflows

### 1. CICD Terraform Container Workflow
This workflow automates the continuous integration and continuous deployment (CICD) process using Terraform within a containerized environment. It ensures consistent and efficient infrastructure provisioning across multiple environments.

### 2. Manual Terraform Deployment Workflow
This workflow facilitates manual Terraform deployments with added checks and balances. It allows for environment-specific deployments with controlled, manual intervention, ensuring that deployments are carried out safely and intentionally.

### 3. Terraform Infrastructure Workflow
This workflow is designed for **pure Terraform infrastructure deployments** (no Docker containers involved). It's perfect for infrastructure modules like backup services, networking, or security configurations. The workflow provides plan-on-PR functionality, auto-deploys to dev, and auto-deploys to production on main branch merges (following org standard).

## Example Usage

These examples show how to call these reusable workflows from your own repos. You'll still need to create a GitHub Actions workflow in your repo, and that will call this reusable workflow.

### Example Usage - CICD Terraform Container Workflow

`.github/workflows/cicd.yml`:
```yaml
name: CICD

on:
  push:
    branches:
      - main
      - develop

jobs:
  cicd-deploy:
    uses: commercesong/org-reusable-workflows/.github/workflows/cicd-terraform-container.yml@main
    with:
      commit_hash: ${{ github.sha }}
      ref: ${{ github.ref }}
      aws_region: "us-east-1"
      image_name: "commercesong/api"
      tf_backend_config_key: "api"
      microservice_path: "services/api"
      platform: "linux/arm64"
      run_tests: true
      test_install_command: "npm install --include=dev"
      test_auto_setup_npmrc: true  # DEPRECATED: This now defaults to true and is optional
      test_command: "npm test"
      test_env: '{"NODE_ENV": "test", "CI": "true"}'
      test_env_file: "env-dev.env"
      test_inject_aws_credentials: true
      test_secret_env_ssm_paths: '["cs/secrets/jwt_secret", "cs/secrets/db_password"]'
      test_execution_role_name: "api-test-role"
      disable_docker_cache: false
      job_timeout_minutes: 60
    secrets:
      aws_account_id_dev: ${{ secrets.AWS_ACCOUNT_ID_DEV }}
      aws_account_id_prod: ${{ secrets.AWS_ACCOUNT_ID_PROD }}
    permissions:
      id-token: write  # Required for OIDC authentication
      contents: read
```

In this example, we've added the following optional parameters:

- `microservice_path`: Path to the microservice directory within your repository. This is useful when you have multiple services in the same repository. Defaults to '.' (root directory).
- `platform`: Platform for Docker build (e.g., linux/amd64, linux/arm64). Defaults to 'linux/arm64'.
- `run_tests`: Set to `true` to enable running tests within the Docker container (only for dev environment).
- `test_install_command`: Specifies the command to install test dependencies. This is optional - if you don't need to install anything before running tests, you can omit this parameter or leave it as an empty string. **Note**: For services using private GitHub packages, it's often simpler to include dev dependencies directly in the container build (using `npm install --include=dev` in your Dockerfile) rather than installing them during test execution. If you take this approach, you would omit the `test_install_command` parameter entirely or set it to an empty string, since the testing dependencies are already installed in the container.
- `test_auto_setup_npmrc`: **DEPRECATED** - This parameter now defaults to `true` and will be ignored in future versions. The workflow automatically creates `.npmrc` with GitHub authentication before running `test_install_command`. This is the recommended solution for services that need to install private GitHub packages during testing. The workflow will automatically create the `.npmrc` file, run your test installation command, and then clean up the `.npmrc` file for security. Defaults to `true`.
- `test_command`: Specifies the command to run the tests.
- `test_env`: A JSON string of environment variables to be set when running the tests.
- `test_env_file`: Path to an environment file containing additional environment variables for testing.
- `test_inject_aws_credentials`: Set to `true` to inject AWS credentials into the test container.
- `test_secret_env_ssm_paths`: A JSON-formatted array of SSM parameter paths for secret environment variables. This simulates how ECS/Lambda would normally inject SSM parameters as environment variables in production. For example, if you pass `["cs/secrets/jwt_secret"]`, the workflow will fetch this value from SSM and create an environment variable `JWT_SECRET` in your test container, similar to how it would work in production. Do not include a leading '/' in these paths.
- `test_execution_role_name`: Name of the role to assume for running tests. This is useful when you want to test with restricted permissions to ensure your application works with the intended IAM role. If not specified, tests will run with the admin credentials (when test_inject_aws_credentials is true).
- `disable_docker_cache`: Set to `true` to force Docker to build the image without using any cached layers. This is useful when you want to ensure a completely fresh build, such as when dependencies might have been updated without version changes. Defaults to `false`.
- `job_timeout_minutes`: Timeout in minutes for each job (build-and-push-dev, deploy-dev, build-and-push-prod, deploy-prod). Defaults to `60`. Increase this for services with long-running test suites.

Note: When using `test_execution_role_name`, the role must have a trust policy allowing the GitHub Actions OIDC role to assume it:
```json
{
    "Effect": "Allow",
    "Principal": {
        "AWS": "arn:aws:iam::${account_id}:role/github-actions-deploy-${environment}"
    },
    "Action": "sts:AssumeRole"
}
```

The workflow will search for and apply all `aws_ecr_repository` and `aws_iam_role` resources before proceeding with the build and test steps. This ensures that necessary infrastructure is in place before the tests begin.

Note: 
1. The environment variables are combined from `test_env`, `test_env_file`, and SSM parameters when running the tests. 
2. Variables in `test_env` take precedence over those in the file if there are conflicts.
3. For SSM parameters, the last part of the path is used as the environment variable name (in uppercase). For example, `cs/secrets/jwt_secret` becomes `JWT_SECRET`.

If you don't want to run tests, you can omit these parameters or set `run_tests` to `false`. Tests are only run in the dev environment.

The workflow will build the Docker image, run the specified tests within the container (with AWS credentials and secret environment variables if specified), and only proceed with pushing and deploying if the tests pass.

### Example Usage - Manual Terraform Deployment

`.github/workflows/manual-terraform-deploy.yml`:
```yaml
name: Manual Deploy

on:
  workflow_dispatch:
    inputs:
      environment:
        description: 'Environment to deploy to'
        required: true
        type: choice
        options:
          - dev
          - prod
      commit_hash:
        description: 'GitHub SHA to deploy'
        required: true
        type: string

jobs:
  manual-deploy:
    uses: commercesong/org-reusable-workflows/.github/workflows/manual-terraform-deploy.yml@main
    with:
      environment: ${{ github.event.inputs.environment }}
      commit_hash: ${{ github.event.inputs.commit_hash }}
      aws_region: "us-east-1"
      image_name: "commercesong/api"
      tf_backend_config_key: "api"
    secrets:
      aws_account_id_dev: ${{ secrets.AWS_ACCOUNT_ID_DEV }}
      aws_account_id_prod: ${{ secrets.AWS_ACCOUNT_ID_PROD }}
    permissions:
      id-token: write  # Required for OIDC authentication
      contents: read
```

### Example Usage - Terraform Infrastructure

`.github/workflows/backup-services.yml`:
```yaml
name: Backup Services Infrastructure

on:
  push:
    branches:
      - main
      - develop
    paths:
      - 'terraform/backup-services/**'
  pull_request:
    branches:
      - main
      - develop
    paths:
      - 'terraform/backup-services/**'
  workflow_dispatch:
    inputs:
      environment:
        description: 'Environment to deploy to'
        required: true
        type: choice
        options:
          - dev
          - prod

jobs:
  backup-services-infrastructure:
    uses: commercesong/org-reusable-workflows/.github/workflows/terraform-infrastructure.yml@main
    with:
      tf_backend_config_key: "backup-services"
      aws_region: "us-east-1"
      commit_hash: ${{ github.sha }}
      ref: ${{ github.ref }}
      terraform_path: "terraform/backup-services"
      terraform_version: "1.8.3"
      enable_plan_comment: true
      auto_apply_dev: true
    secrets:
      aws_account_id_dev: ${{ secrets.AWS_ACCOUNT_ID_DEV }}
      aws_account_id_prod: ${{ secrets.AWS_ACCOUNT_ID_PROD }}
    permissions:
      id-token: write  # Required for OIDC authentication
      contents: read
```

**Key features of this workflow:**

- **Path-based triggers**: Only runs when files in the specified Terraform directory change
- **Plan on PRs**: Shows Terraform plan output as comments on pull requests
- **Auto-deploy dev**: Automatically applies changes to dev environment on develop branch merges
- **Auto-deploy prod**: Automatically applies changes to prod environment on main branch merges (org standard)
- **Manual dispatch**: Allows manual deployment to any environment via GitHub UI
- **Pure Terraform**: No Docker or container complexity

**Parameters:**

- `tf_backend_config_key`: The S3 key prefix for your Terraform state (e.g., "backup-services"). **Important:** Do NOT include "/terraform.tfstate" in this value - the workflow automatically appends it to create the full backend key.
- `terraform_path`: Path to your Terraform directory within the repository
- `tfvars_path`: Path to tfvars files relative to terraform_path (defaults to "."). Use ".." for shared parent directory tfvars
- `terraform_version`: Version of Terraform to use (defaults to "1.8.3")
- `enable_plan_comment`: Whether to comment Terraform plans on PRs (defaults to true)
- `auto_apply_dev`: Whether to auto-apply to dev environment (defaults to true)

**Tfvars Configuration:**

The workflow supports two approaches for tfvars files:

- **Module-specific**: Use `tfvars_path: "."` with `env-dev.tfvars` in each module directory
- **Shared parent**: Use `tfvars_path: ".."` with shared `../env-dev.tfvars` for common variables

**Deployment Flow:**

1. **Pull Requests**: Runs `terraform plan` and comments the results on the PR
2. **Develop Branch**: Auto-deploys to dev environment after merge
3. **Main Branch**: Auto-deploys to production environment after merge
4. **Manual Dispatch**: Deploy to any environment on-demand via GitHub UI

## Pre-Requisites for Repos Using these Workflows

To successfully use these reusable workflows, your repository must meet the following requirements:

### 1. Repository Structure
Your repository can be organized in one of two ways:

#### Single Service Repository
For repositories containing a single service, maintain the following structure:
```
your-repo/
├── terraform/          # Terraform configuration files
│   ├── env-dev.tfvars
│   └── env-prod.tfvars
├── Dockerfile         # Docker configuration (for container workflows)
└── *                 # Application source code files
```

#### Pure Infrastructure Repository (for Terraform Infrastructure Workflow)
For repositories containing only infrastructure (no containers), maintain this structure:
```
your-repo/
├── terraform/          # Terraform modules directory
│   ├── backup-services/
│   │   ├── main.tf
│   │   ├── variables.tf
│   │   ├── outputs.tf
│   │   ├── env-dev.tfvars
│   │   └── env-prod.tfvars
│   ├── networking/
│   │   ├── main.tf
│   │   ├── env-dev.tfvars
│   │   └── env-prod.tfvars
│   └── security/
│       ├── main.tf
│       ├── env-dev.tfvars
│       └── env-prod.tfvars
└── .github/workflows/  # CI/CD workflows for each module
```

#### Multi-Service Repository
For repositories containing multiple services, maintain the following structure:
```
your-repo/
├── services/
│   ├── service1/
│   │   ├── terraform/    # Service1 Terraform configuration
│   │   │   ├── env-dev.tfvars
│   │   │   └── env-prod.tfvars
│   │   ├── Dockerfile   # Service1 Docker configuration
│   │   └── *            # Service1 source code files
│   └── service2/
│       ├── terraform/    # Service2 Terraform configuration
│       │   ├── env-dev.tfvars
│       │   └── env-prod.tfvars
│       ├── Dockerfile   # Service2 Docker configuration
│       └── *            # Service2 source code files
```

When using a multi-service repository structure, specify the `microservice_path` parameter in your workflow (e.g., `microservice_path: "services/service1"`).

### 2. Terraform Subdirectory
Your repository must include a `terraform` subdirectory at the root level. This directory will contain all Terraform configuration files necessary for infrastructure deployment.

### 3. Environment Specific Variable Files
Within the `terraform` subdirectory, you must include environment-specific variable files. These files should follow the naming convention:

For example:
- `env-dev.tfvars`
- `env-prod.tfvars`

These variable files will be used by Terraform during the deployment process to apply environment-specific configurations.

### 4. Ensuring Accurate Version Deployment with Image Variables

When integrating your application with this reusable workflow, it's essential to ensure that your Terraform configuration includes the image_name and image_tag variables. The image_name variable, as shown in the example below, should be passed to the reusable workflow and specify the base name of your Docker image. Meanwhile, the image_tag variable must be defined in your Terraform configuration to specify the exact version of the image to be deployed.

By implementing these variables, you ensure that the correct version of your application is deployed. Without properly setting the image_tag, the deployment may not update to the intended version, potentially leaving an older version running. Thus, incorporating these variables into your Terraform is not merely a convenience but a necessary step to guarantee that your deployment reflects the desired container version.

Here's an example Terraform fragment of how you would use the image_name and image_tag variables when configuring your ECS task definition.

```hcl
resource "aws_ecs_task_definition" "api" {
  family                   = "api"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.container_cpu
  memory                   = var.container_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution_role.arn
  container_definitions    = jsonencode([
    {
      name      = "api",
      image     = "${aws_ecr_repository.ecr_repo.repository_url}:${var.image_tag}",
```

### 5. Required Secrets
The workflows expect these two GitHub Actions secrets to resolve at runtime:

- **AWS_ACCOUNT_ID_DEV** (for the `dev` environment)
- **AWS_ACCOUNT_ID_PROD** (for the `prod` environment)

**Status: already set at the org level on all 4 trusted orgs** (commercesong, enterprisevibecoding, elevatorfunrooms, forgotpw) with `ALL` visibility, so any repo in those orgs inherits them automatically — **no per-repo secret setup needed**.

To verify on any of those orgs:
```bash
gh secret list --org <org-name>
```
You should see both secrets with timestamp and `ALL` visibility.

The values, where they live, and how to set them on a brand-new org are
documented in [`commercesong/infrastructure/README.md`](https://github.com/commercesong/infrastructure/blob/main/README.md#github-actions-org-secrets).

AWS authentication itself is OIDC — no long-lived AWS access keys are stored anywhere. The workflows use the `github-actions-deploy-dev` and `github-actions-deploy-prod` IAM roles, assumed via the OIDC provider configured in [`commercesong/infrastructure/github-oidc/`](https://github.com/commercesong/infrastructure/tree/main/github-oidc).

### 6. OIDC Authentication Setup
These workflows use AWS OIDC for authentication. Before using the workflows, ensure the OIDC infrastructure is deployed in your AWS accounts. See `commercesong/infrastructure/github-oidc/README.md` for setup instructions.

Calling workflows must include the following permissions block:
```yaml
permissions:
  id-token: write  # Required for OIDC authentication
  contents: read
```

## Initial Setup for Reusable Workflows

> **⚠️ Most of this section is informational right now.** This repo is intentionally **public** so that any GitHub org can reference these workflows via `uses:`. On GitHub Free, cross-org sharing of *private* reusable workflows isn't supported — making the repo public is the standard workaround. The actual security boundary is the OIDC trust policy in the private [`commercesong/infrastructure`](https://github.com/commercesong/infrastructure) repo, which restricts AWS role assumption to specific GitHub orgs.
>
> The GitHub UI access steps below would only matter if the repo were ever made **private again** (which would require either upgrading to GitHub Enterprise or using a sync mechanism). Keeping them here as a runbook for that scenario.

### GitHub Configuration *(only applies if repo is private)*

* Organization-Level Setup: In your organization settings, go to Actions > General and select Allow all actions and reusable workflows to enable sharing across the organization.

* Repository-Level Setup: In this repository's settings, under Actions > General, scroll to the Access section. Change "Control how this repository is used by GitHub Actions workflows" to "Accessible from repositories in other organizations" and add the organizations that should have access. *(Note: this option requires GitHub Enterprise — it's not available on Free or Team plans.)*

### Cross-Organization Access (AWS / OIDC Trust List)

The following GitHub organizations are trusted by the AWS OIDC IAM role and can therefore deploy via these workflows:
- commercesong
- enterprisevibecoding
- elevatorfunrooms
- forgotpw

This list is the canonical source of truth for the AWS-side trust and must stay in sync with the `github_orgs` default in
[`commercesong/infrastructure/terraform-modules/github-oidc/variables.tf`](https://github.com/commercesong/infrastructure/blob/main/terraform-modules/github-oidc/variables.tf).
While this repo is public, no GitHub-side access list is needed — the OIDC trust policy is the only gate. If the repo ever goes private again, the GitHub-side "Accessible from" setting would also need to include each org (see GitHub Configuration above).

### AWS OIDC Setup

Before the workflows can authenticate to AWS, you must deploy the OIDC infrastructure:

1. Navigate to `commercesong/infrastructure/github-oidc`
2. Follow the instructions in the README to deploy to both dev and prod AWS accounts
3. This creates the `github-actions-deploy-dev` and `github-actions-deploy-prod` IAM roles

These steps are only required as part of the initial configuration and must be completed to allow other repositories in the organization to reference and use these reusable workflows.

## IAM Role Configuration for Testing

When using `test_execution_role_name`, you need to configure your Lambda or ECS execution role in Terraform to include the GitHub Actions OIDC role in its trust policy. Here's how:

### For Lambda Functions:
```hcl
resource "aws_iam_role" "lambda_exec_role" {
  name = "${var.service_name}-lambda-exec-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # Allow Lambda service to assume this role
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      },
      {
        # Allow GitHub Actions OIDC role to assume this role for testing
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${var.aws_account_id}:role/github-actions-deploy-${var.environment}"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
}
```

### For ECS Tasks:
```hcl
resource "aws_iam_role" "ecs_task_role" {
  name = "${var.service_name}-ecs-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # Allow ECS tasks to assume this role
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      },
      {
        # Allow GitHub Actions OIDC role to assume this role for testing
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${var.aws_account_id}:role/github-actions-deploy-${var.environment}"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
}
```

The workflow will automatically:
1. Always pre-apply ECR repository resources
2. When `test_execution_role_name` is specified:
   - Pre-apply all IAM-related resources (roles, policies, and attachments)
   - This ensures any IAM permission changes are applied before running tests
3. Assume the role during test execution
4. Use the role's permissions to validate that your application works with the intended IAM permissions

This ensures your tests run with the same permissions that your application will have in production, and any IAM changes are applied before testing begins.

Note: IAM resources are only pre-applied in the development environment when running tests with a specified execution role. The production environment only pre-applies ECR resources.

## Troubleshooting

### Troubleshooting: Reusable Workflow Rerun Behavior Differences

#### Issue: "Re-run failed jobs" vs "Re-run all jobs" behave differently with reusable workflows

When debugging authentication or other issues with reusable workflows, you may notice that **"Re-run all jobs"** resolves problems that persist when using **"Re-run failed jobs"**. This is documented GitHub Actions behavior, not a bug.

#### **Key Insight: Different Workflow Context Resolution**

According to GitHub's official documentation:
- **"Re-run failed jobs"** uses the reusable workflow from the **same commit SHA** of the first attempt
- **"Re-run all jobs"** uses the reusable workflow from the **specified reference** (fresher context)

This difference can affect:
- Authentication token refresh
- Workflow context resolution  
- Dependency resolution between jobs
- Environment variable availability

#### **Recommended Troubleshooting Approach**

**Important for AI assistants**: When helping troubleshoot workflow issues, always ask the user HOW they are rerunning the workflow (via "Re-run failed jobs" or "Re-run all jobs" button in GitHub Actions UI) as this significantly affects the behavior.

If you encounter persistent authentication or workflow issues:

1. **First try**: "Re-run all jobs" instead of "Re-run failed jobs"
2. **If that works**: The issue is likely related to workflow context differences between the two rerun modes
3. **If that doesn't work**: The issue is likely with your workflow configuration itself

#### **Why This Happens**

The different behavior occurs because GitHub Actions handles workflow context, dependency resolution, and authentication token refresh differently between the two rerun modes. When rerunning all jobs, GitHub Actions fetches a fresh workflow context from the current reference, which can resolve authentication token issues or dependency problems that persist when using the cached context from the original run.

#### **When to Use Each Option**

*Note: If you're working with an AI assistant to troubleshoot, be sure to mention which rerun method you're using, as the choice affects the workflow behavior.*

- **Use "Re-run all jobs"** when:
  - Debugging authentication issues with reusable workflows
  - You've made changes to the workflow files since the original run
  - You want to ensure fresh context and dependencies

- **Use "Re-run failed jobs"** when:
  - You're confident the workflow context is correct
  - You want to save CI/CD time by not re-running successful jobs
  - The failure is clearly related to the specific job logic, not workflow context

### Troubleshooting: npm 401 Unauthorized errors with GitHub Packages

#### Issue: 401 Unauthorized when installing GitHub packages during testing

If you encounter an error like this during test execution in CI/CD workflows:

```
npm error 401 Unauthorized - GET https://npm.pkg.github.com/@commercesong%2fllm-proxy-client - authentication token not provided
```

#### **Recommended Solution: Use `test_auto_setup_npmrc`**

The easiest and most reliable way to fix this is to use the built-in GitHub packages authentication:

```yaml
# In your .github/workflows/cicd.yml
jobs:
  cicd-deploy:
    uses: commercesong/org-reusable-workflows/.github/workflows/cicd-terraform-container.yml@main
    with:
      # ... other parameters ...
      run_tests: true
      test_command: "npm test"
      test_install_command: "npm install --include=dev && npm install -g mocha"
      test_auto_setup_npmrc: true  # DEPRECATED: This now defaults to true and is optional
      test_inject_aws_credentials: true
```

**What the automatic `.npmrc` setup does:** *(now enabled by default)*
1. **Before** running `test_install_command`, automatically creates `.npmrc` with GitHub authentication
2. **Runs** your `test_install_command` with full access to private GitHub packages
3. **After** test completion, automatically removes `.npmrc` for security

**Note:** The `test_auto_setup_npmrc` parameter is now **DEPRECATED** and defaults to `true`. You can omit this parameter from your workflow configurations as the `.npmrc` setup now happens automatically.

**Benefits:**
- ✅ **Zero configuration** - just set one boolean parameter
- ✅ **Automatic cleanup** - .npmrc is removed after testing for security
- ✅ **Works with microservice_path** - handles directory structure correctly
- ✅ **Reliable authentication** - uses the same GitHub token as Docker builds
- ✅ **Clear error messages** - validates token availability before proceeding

#### Root Cause (for troubleshooting)

This error typically occurs due to one of these issues:

**1. Version mismatch between package.json and package-lock.json**
This is caused by **version ranges** (`^`, `~`) with private GitHub packages that don't match the locked versions.

**Common Scenario:**
```json
// package.json
"@commercesong/llm-proxy-client": "^1.5.0"  // ❌ Range allows 1.5.x

// package-lock.json  
"@commercesong/llm-proxy-client": "1.5.0"   // Exact version locked
```

Even though both reference `1.5.0`, npm sees this as a mismatch because:
- `^1.5.0` means "1.5.0 or any compatible newer version"
- `1.5.0` means "exactly 1.5.0"

**How this happens step-by-step:**
- You update a dependency version in `package.json` (e.g., from `"^1.3.1"` to `"^1.3.6"`)
- You don't update the `package-lock.json` file, which still references the older version
- When npm runs `npm install --include=dev && npm install -g mocha`, it sees the newer version requirement in package.json
- Even though an older version is already installed, npm tries to fetch the newer version from the registry
- Without authentication credentials (.npmrc), this request fails with a 401 error

**2. Missing .npmrc during test execution**
Docker builds have access to GITHUB_TOKEN and create .npmrc, but it's removed before testing.

**3. microservice_path usage**
Tests run from a subdirectory where .npmrc doesn't exist.

#### Alternative Solutions (if you can't use test_auto_setup_npmrc)

**Option 1: Fix version mismatches**
```json
// Change package.json from version range to exact version
"@commercesong/llm-proxy-client": "1.5.0"  // ✅ Exact version
// Instead of: "^1.5.0"  // ❌ Range that triggers version checks
```

**Or update package-lock.json to match package.json:**
```bash
# Update package-lock.json to match package.json
npm update @commercesong/llm-proxy-client

# Or regenerate package-lock.json completely
rm package-lock.json && npm install
```

**Note:** This approach can fix the issue when the problem is purely version mismatches, especially since `npm install -g mocha` installs public packages and npm tries to resolve all dependencies during the process.

**Option 2: Manual .npmrc recreation (unreliable)**
```yaml
test_install_command: "echo '//npm.pkg.github.com/:_authToken=${GITHUB_TOKEN}' > .npmrc && echo '@commercesong:registry=https://npm.pkg.github.com' >> .npmrc && npm install --include=dev && npm install -g mocha && rm -f .npmrc"
```
*Note: This approach has proven unreliable due to shell escaping issues, timing problems, and authentication complexity. We strongly recommend using `test_auto_setup_npmrc: true` instead.*

**Option 3: Include dev dependencies in container build**
```dockerfile
# In your Dockerfile - install dev dependencies during build
RUN echo "//npm.pkg.github.com/:_authToken=${GITHUB_TOKEN}" > .npmrc && \
    echo "@commercesong:registry=https://npm.pkg.github.com" >> .npmrc && \
    npm cache clean --force && \
    npm install --include=dev && \
    npm cache clean --force && \
    rm -f .npmrc
```

Then omit `test_install_command`:
```yaml
test_install_command: ""  # Dependencies already in container
test_command: "npm test"
```

#### Prevention

**For private GitHub packages:**
- ✅ Always use exact versions: `"1.5.0"`
- ❌ Avoid version ranges: `"^1.5.0"`, `"~1.5.0"`

**For all packages:**
- Keep package.json and package-lock.json in sync
- No need to add `permissions` block to your workflow (the reusable workflow handles this)

**Why exact versions for private packages?**
During Docker build, npm has access to GITHUB_TOKEN and can authenticate. During test execution (`test_install_command`), the container has the token but the `.npmrc` file was removed after the build, so version ranges that trigger version checks will fail without recreating the authentication.

