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
        compatible = copy.deepcopy(CONFIG)
        del compatible[True]['workflow_call']['inputs']['terraform_version']
        for job in ['build-and-push-dev', 'build-and-push-prod', 'deploy-dev', 'deploy-prod']:
            terraform_step(compatible, job)['with']['terraform_version'] = terraform_step(BASELINE, job)['with']['terraform_version']
        self.assertEqual(compatible, BASELINE)


if __name__ == '__main__':
    unittest.main()
