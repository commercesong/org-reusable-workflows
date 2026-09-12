"""Exercise the actual inline workflow planner; no simulated AWS implementation."""

import ast
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import call, patch

import yaml


REPO = Path(__file__).resolve().parents[1]
WORKFLOW = REPO / '.github/workflows/static-site-deploy.yml'
CONFIG = yaml.safe_load(WORKFLOW.read_text())
STEPS = CONFIG['jobs']['deploy-configured']['steps']
PLANNER_CODE = next(step['run'] for step in STEPS if step['name'] == 'Validate S3 upload plan')
# Import the real function definitions, without executing the workflow entrypoint.
tree = ast.parse(PLANNER_CODE)
tree.body = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef))]
namespace = {}
exec(compile(tree, str(WORKFLOW), 'exec'), namespace)
make_plan = namespace['make_plan']


class UploadPlanTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name).resolve()
        self.site = self.workspace / 'site'
        self.site.mkdir()
        (self.site / 'index.html').write_text('<h1>Site</h1>')
        (self.site / 'contact.vcf').write_text('BEGIN:VCARD\nEND:VCARD\n')
        (self.site / 'app.js').write_text('console.log("site")')

    def plan(self, rules, **kwargs):
        return make_plan(json.dumps(rules), kwargs.get('source_path', 'site'),
                         kwargs.get('bucket', 'example-site-dev'),
                         kwargs.get('delete_removed', True), self.workspace)

    def copy_rule(self, **kwargs):
        return dict(operation='s3_copy', source_file='contact.vcf',
                    destination_key='downloads/contact.vcf', **kwargs)

    def sync_rule(self, **kwargs):
        return dict(operation='s3_sync', source_directory='.', destination_prefix='', **kwargs)

    def test_order_headers_alias_and_literal_arguments(self):
        headers = {'content_type': 'text/vcard', 'content_disposition': 'attachment; filename="contact.vcf"'}
        rules = [self.sync_rule(exclude=['*.html', '*.vcf'], cache_control='public,max-age=3600'),
                 self.copy_rule(**headers),
                 {**self.copy_rule(**headers), 'destination_key': 'contact.vcf.'},
                 self.sync_rule(exclude=['*'], include=['*.html'], cache_control='no-cache')]
        commands = self.plan(rules)
        self.assertEqual([c[2] for c in commands], ['sync', 'cp', 'cp', 'sync'])
        self.assertEqual(commands[2][4], 's3://example-site-dev/contact.vcf.')
        self.assertEqual(commands[1][-4:], ['--content-type', 'text/vcard', '--content-disposition', headers['content_disposition']])
        self.assertEqual(commands[3][-6:], ['--exclude', '*', '--include', '*.html', '--cache-control', 'no-cache'])
        self.assertTrue(all('--delete' not in command for command in commands))

    def test_artifact_only_retains_existing_delete_setting(self):
        for delete in (True, False):
            command, = make_plan('', 'site', 'example-site-dev', delete, self.workspace)
            self.assertEqual('--delete' in command, delete)

    def test_rule_deletion_is_explicit_and_independent_of_legacy_input(self):
        for legacy in (True, False):
            for explicit in (True, False):
                command, = self.plan([self.sync_rule(delete_removed=explicit)], delete_removed=legacy)
                self.assertEqual('--delete' in command, explicit)

    def test_prefix_stays_directory_and_copy_stays_exact_key(self):
        command, = self.plan([{**self.sync_rule(), 'destination_prefix': 'assets'}])
        self.assertEqual(command[4], 's3://example-site-dev/assets/')
        command, = self.plan([self.copy_rule()])
        self.assertEqual(command[4], 's3://example-site-dev/downloads/contact.vcf')

    def test_rejects_invalid_configuration_with_rule_number(self):
        cases = [
            ({'operation': 'copy'}, 'Rule 1: unsupported operation'),
            ({**self.copy_rule(), 'command': 'anything'}, 'unsupported field'),
            ({**self.copy_rule(), 'include': ['*']}, 'unsupported field'),
            ({**self.copy_rule(), 'source_file': 'missing'}, 'missing file'),
            ({**self.copy_rule(), 'source_file': '../outside'}, 'relative path'),
            ({**self.copy_rule(), 'destination_key': 's3://other/key'}, 'relative path'),
            ({**self.copy_rule(), 'destination_key': '/key'}, 'relative path'),
            ({**self.copy_rule(), 'destination_key': 'dir/'}, 'one S3 object'),
            ({**self.copy_rule(), 'destination_key': './key'}, 'dot path'),
            (self.sync_rule(delete_removed='false'), 'must be a boolean'),
            (self.sync_rule(include='*.html'), 'array of strings'),
            (self.sync_rule(exclude=[5]), 'non-empty string'),
            (self.copy_rule(cache_control='bad\nheader'), 'control characters'),
            ({**self.copy_rule(), 'source_file': '.'}, 'missing file'),
            ({**self.sync_rule(), 'source_directory': 'index.html'}, 'missing directory'),
            ({'operation': ['s3_copy']}, 'unsupported operation'),
        ]
        for rule, message in cases:
            with self.subTest(rule=rule), self.assertRaisesRegex(ValueError, message):
                self.plan([rule])

    def test_valid_first_rule_does_not_hide_invalid_later_rule(self):
        with self.assertRaisesRegex(ValueError, 'Rule 2.*missing file'):
            self.plan([self.copy_rule(), {**self.copy_rule(), 'source_file': 'missing'}])

    def test_rejects_invalid_json_shapes_and_duplicates(self):
        for raw in ('[', '{}', 'null', '[]', '[null]', '[{"operation":"s3_sync","operation":"s3_copy"}]'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                make_plan(raw, 'site', 'example-site-dev', True, self.workspace)

    def test_rejects_source_root_escape_and_invalid_bucket(self):
        for path in ('../', '/tmp', '', 'missing'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.plan([self.copy_rule()], source_path=path)
        with self.assertRaisesRegex(ValueError, 'S3 bucket name'):
            self.plan([self.copy_rule()], bucket='s3://example-site-dev/prefix')

    def test_rejects_symbolic_links_before_sync_or_copy(self):
        (self.site / 'link').symlink_to(self.site / 'contact.vcf')
        for rule in (self.sync_rule(), {**self.copy_rule(), 'source_file': 'link'}):
            with self.subTest(rule=rule), self.assertRaisesRegex(ValueError, 'symbolic links'):
                self.plan([rule])

    def test_s3_values_are_literal_arguments_not_shell_code(self):
        command, = self.plan([self.copy_rule(cache_control='$(touch /tmp/should-not-exist)')])
        self.assertEqual(command[-1], '$(touch /tmp/should-not-exist)')
        executor = next(step['run'] for step in STEPS if step['name'] == 'Execute S3 upload plan')
        self.assertIn('subprocess.run(command, check=True)', executor)
        self.assertNotIn('shell=True', executor)

    def test_executor_stops_and_propagates_upload_failure(self):
        commands = self.plan([self.copy_rule(), self.copy_rule(), self.sync_rule()])
        (self.workspace / 'static-site-s3-plan.json').write_text(json.dumps(commands))
        executor = next(step['run'] for step in STEPS if step['name'] == 'Execute S3 upload plan')
        failure = subprocess.CalledProcessError(1, commands[1])
        output = io.StringIO()
        # Inject only the failure; successful AWS behavior has real S3 coverage.
        with patch.dict(os.environ, {'RUNNER_TEMP': str(self.workspace)}), \
                patch('subprocess.run', side_effect=[None, failure]) as run, redirect_stdout(output):
            with self.assertRaises(subprocess.CalledProcessError) as raised:
                exec(compile(executor, str(WORKFLOW), 'exec'), {})
        self.assertIs(raised.exception, failure)
        self.assertIn('Rule 1/3 completed successfully', output.getvalue())
        self.assertIn('Rule 2/3: aws s3 cp', output.getvalue())
        self.assertNotIn('Rule 2/3 completed successfully', output.getvalue())
        self.assertNotIn('S3 upload plan completed:', output.getvalue())
        self.assertEqual(run.call_args_list, [call(commands[0], check=True),
                                              call(commands[1], check=True)])


class CompatibilityTests(unittest.TestCase):
    def test_documented_example_rules_compile(self):
        documentation = (REPO / 'docs/static-site-s3-uploads.md').read_text()
        example = documentation.split('```yaml\n', 1)[1].split('```', 1)[0]
        caller = yaml.safe_load(example)['jobs']['content']
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary).resolve()
            site = workspace / 'site'
            site.mkdir()
            (site / 'contact.vcf').write_text('BEGIN:VCARD\nEND:VCARD\n')
            (site / 'index.html').write_text('<h1>Documentation fixture</h1>')
            plan = make_plan(caller['with']['s3_upload_rules'], 'site', 'my-site-dev', True, workspace)
            self.assertEqual([command[2] for command in plan], ['sync', 'cp', 'cp', 'sync'])
            self.assertEqual(plan[2][4], 's3://my-site-dev/contact.vcf.')

    def test_original_jobs_unchanged_except_opt_in_condition(self):
        # Frozen pre-extension revision: preserve the public contract and old steps.
        baseline = yaml.safe_load(subprocess.check_output([
            'git', 'show', '6f9c331:.github/workflows/static-site-deploy.yml'], cwd=REPO, text=True))
        for job_id in ('deploy-dev', 'deploy-prod'):
            old = dict(baseline['jobs'][job_id])
            new = dict(CONFIG['jobs'][job_id])
            condition = new.pop('if')
            original_condition = old.pop('if')
            if job_id == 'deploy-prod':
                original_condition = f'({original_condition})'
            self.assertEqual(old, new)
            self.assertEqual(condition, original_condition +
                             " && inputs.github_actions_artifact_name == '' && inputs.s3_upload_rules == ''")
        self.assertEqual(CONFIG['permissions'], baseline['permissions'])
        # PyYAML uses YAML 1.1, where the unquoted key `on` is parsed as True.
        for name, definition in baseline[True]['workflow_call']['inputs'].items():
            self.assertEqual(CONFIG[True]['workflow_call']['inputs'][name], definition)


if __name__ == '__main__':
    unittest.main()
