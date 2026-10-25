"""Verify the optional container deploy-version interface preserves legacy callers.

Actual GitHub invocation and Terraform deployment are proved by the collector dev CI;
these checks isolate selection and backward compatibility without mocking GitHub/AWS.
"""
import copy
from pathlib import Path
import subprocess
import unittest

import yaml

REPO = Path(__file__).resolve().parents[1]
WORKFLOW = '.github/workflows/cicd-terraform-container.yml'
CONFIG = yaml.safe_load((REPO / WORKFLOW).read_text())
BASELINE = yaml.safe_load(subprocess.check_output(
    ['git', 'show', f'5d8dd6d:{WORKFLOW}'], cwd=REPO, text=True))

AUTH_BASELINE = yaml.safe_load(subprocess.check_output(
    ['git', 'show', f'85ef296:{WORKFLOW}'], cwd=REPO, text=True))


def without_public_ecr_auth(config):
    compatible = copy.deepcopy(config)
    compatible[True]['workflow_call']['inputs'].pop('public_ecr_login', None)
    for job in ['build-and-push-dev', 'build-and-push-prod']:
        compatible['jobs'][job]['steps'] = [step for step in compatible['jobs'][job]['steps']
            if step.get('name') != 'Login to public Amazon ECR']
    return compatible


def terraform_step(config, job):
    return next(step for step in config['jobs'][job]['steps'] if step['name'] == 'Setup Terraform')


class ContainerTerraformVersionTests(unittest.TestCase):
    def test_omitted_input_preserves_legacy_deploy_version(self):
        # PyYAML's YAML 1.1 parser represents GitHub's `on` key as boolean True.
        value = CONFIG[True]['workflow_call']['inputs']['terraform_version']
        self.assertEqual(value, {
            'description': "Terraform version for all build/apply jobs; omit to preserve each job's legacy version",
            'required': False, 'type': 'string', 'default': ''})

    def test_all_build_and_apply_jobs_use_the_selected_version(self):
        for job in ['build-and-push-dev', 'build-and-push-prod', 'deploy-dev', 'deploy-prod']:
            legacy = terraform_step(BASELINE, job)['with']['terraform_version']
            self.assertEqual(terraform_step(CONFIG, job)['with']['terraform_version'],
                             "${{ inputs.terraform_version || '" + legacy + "' }}")

    def test_every_other_workflow_setting_matches_pre_extension_baseline(self):
        compatible = without_public_ecr_auth(CONFIG)
        del compatible[True]['workflow_call']['inputs']['terraform_version']
        for job in ['build-and-push-dev', 'build-and-push-prod', 'deploy-dev', 'deploy-prod']:
            terraform_step(compatible, job)['with']['terraform_version'] = terraform_step(BASELINE, job)['with']['terraform_version']
        self.assertEqual(compatible, BASELINE)


class ContainerPublicEcrAuthenticationTests(unittest.TestCase):
    def test_public_authentication_is_an_optional_default_false_input(self):
        self.assertEqual(CONFIG[True]['workflow_call']['inputs'].get('public_ecr_login'), {
            'description': 'Authenticate public ECR base-image pulls with the existing AWS role',
            'required': False, 'type': 'boolean', 'default': False})

    def test_opt_in_authenticates_only_before_builds_with_no_anonymous_fallback(self):
        for job, config in CONFIG['jobs'].items():
            steps = config['steps']
            matches = [step for step in steps if step.get('name') == 'Login to public Amazon ECR']
            if job not in ['build-and-push-dev', 'build-and-push-prod']:
                self.assertEqual(matches, [])
                continue
            self.assertEqual(len(matches), 1)
            step = matches[0]
            self.assertEqual(step.get('if'), 'inputs.public_ecr_login')
            self.assertEqual(step['run'], 'set -euo pipefail\n'
                'aws ecr-public get-login-password --region us-east-1 | '
                'docker login --username AWS --password-stdin public.ecr.aws\n')
            names = [step.get('name') for step in steps]
            self.assertLess(names.index('Set up AWS credentials'), names.index(step['name']))
            self.assertLess(names.index('Login to Amazon ECR'), names.index(step['name']))
            self.assertLess(names.index(step['name']), names.index('Build Docker image'))

    def test_omitted_input_preserves_every_existing_workflow_setting(self):
        self.assertEqual(without_public_ecr_auth(CONFIG), AUTH_BASELINE)


if __name__ == '__main__':
    unittest.main()
