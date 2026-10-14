from pathlib import Path
"""TDD tests for aegis_core.enforcement — CI outcome report generator."""
import json
import os
import sys
import textwrap
import pytest
from aegis_core.yaml import dump_frontmatter

REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))


def _make_rule(rules_dir, name, target_paths, rule_type='invariant'):
    """Helper: create a minimal rule .md file with frontmatter."""
    rule_path = os.path.join(rules_dir, f'{name}.md')
    frontmatter = {
        'name': name,
        'type': rule_type,
        'target_paths': target_paths,
        'fitness': {
            'triggers': 0,
            'true_positives': 0,
            'false_positives': 0,
            'score': None,
        },
    }
    content = dump_frontmatter(frontmatter, body=f"# {name}\n\nTest rule.\n")
    os.makedirs(os.path.dirname(rule_path), exist_ok=True)
    with open(rule_path, 'w', encoding='utf-8') as f:
        f.write(content)
    return rule_path


class TestRuleMatching:
    """Rules are matched to changed files via target_paths globs."""

    def test_matched_rules_have_target_paths(self, tmp_path):
        """Only rules whose target_paths match a changed file appear in report."""
        from aegis_core.enforcement import generate_ci_report

        rules_dir = tmp_path / '.aegis' / 'rules'
        _make_rule(str(rules_dir / 'boundaries'), 'boundary-core', ['aegis_core/*'], rule_type='boundary')
        _make_rule(str(rules_dir / 'invariants'), 'inv-docs', ['docs/*'], rule_type='invariant')
        _make_rule(str(rules_dir / 'invariants'), 'inv-tests', ['tests/*'], rule_type='invariant')

        report = generate_ci_report(
            workspace=str(tmp_path),
            changed_files=['aegis_core/metrics.py'],
            test_passed=True,
        )

        rule_names = [r['rule'] for r in report['matched_rules']]
        assert 'boundary-core' in rule_names
        assert 'inv-docs' not in rule_names
        assert 'inv-tests' not in rule_names

    def test_no_matches_produces_empty_report(self, tmp_path):
        """Changed files matching no rules → empty matched_rules list."""
        from aegis_core.enforcement import generate_ci_report

        rules_dir = tmp_path / '.aegis' / 'rules' / 'invariants'
        _make_rule(str(rules_dir), 'inv-docs', ['docs/*'])

        report = generate_ci_report(
            workspace=str(tmp_path),
            changed_files=['README.md'],
            test_passed=True,
        )

        assert report['matched_rules'] == []

    def test_multiple_rules_match_same_file(self, tmp_path):
        """Multiple rules can match the same changed file."""
        from aegis_core.enforcement import generate_ci_report

        rules_dir = tmp_path / '.aegis' / 'rules' / 'invariants'
        _make_rule(str(rules_dir), 'rule-a', ['aegis_core/*'])
        _make_rule(str(rules_dir), 'rule-b', ['aegis_core/metrics*.py'])

        report = generate_ci_report(
            workspace=str(tmp_path),
            changed_files=['aegis_core/metrics.py'],
            test_passed=True,
        )

        rule_names = [r['rule'] for r in report['matched_rules']]
        assert 'rule-a' in rule_names
        assert 'rule-b' in rule_names

    def test_generate_ci_report_defaults_changed_files_when_none(self, tmp_path):
        """Calling generate_ci_report with changed_files=None must not raise TypeError."""
        from aegis_core.enforcement import generate_ci_report

        rules_dir = tmp_path / '.aegis' / 'rules' / 'invariants'
        _make_rule(str(rules_dir), 'inv-core', ['aegis_core/*'])

        report = generate_ci_report(
            workspace=str(tmp_path),
            changed_files=None,
            test_passed=True,
        )
        assert report['changed_files'] == []
        assert report['matched_rules'] == []
        assert '## 🛡️ Aegis CI Outcome Report' in report['summary']


class TestCreditWeights:
    """Credit weights are conserved per changed file (1/N matching rules)."""

    def test_credit_weights_conserved(self, tmp_path):
        """If 2 rules match the same file, each gets credit_weight = 0.5."""
        from aegis_core.enforcement import generate_ci_report

        rules_dir = tmp_path / '.aegis' / 'rules' / 'invariants'
        _make_rule(str(rules_dir), 'rule-a', ['aegis_core/*'])
        _make_rule(str(rules_dir), 'rule-b', ['aegis_core/*'])

        report = generate_ci_report(
            workspace=str(tmp_path),
            changed_files=['aegis_core/metrics.py'],
            test_passed=True,
        )

        total_credit = sum(r['credit_weight'] for r in report['matched_rules'])
        assert abs(total_credit - 1.0) < 0.01, f'Credit sum {total_credit} != 1.0'

    def test_sole_rule_gets_full_credit(self, tmp_path):
        """A single matching rule gets credit_weight = 1.0."""
        from aegis_core.enforcement import generate_ci_report

        rules_dir = tmp_path / '.aegis' / 'rules' / 'invariants'
        _make_rule(str(rules_dir), 'rule-solo', ['aegis_core/*'])

        report = generate_ci_report(
            workspace=str(tmp_path),
            changed_files=['aegis_core/metrics.py'],
            test_passed=True,
        )

        assert len(report['matched_rules']) == 1
        assert report['matched_rules'][0]['credit_weight'] == 1.0


class TestSignalSemantics:
    """CI pass → trigger, CI fail → fp for all matched rules."""

    def test_pass_generates_trigger_signals(self, tmp_path):
        """When tests pass, matched rules get signal='trigger'."""
        from aegis_core.enforcement import generate_ci_report

        rules_dir = tmp_path / '.aegis' / 'rules' / 'invariants'
        _make_rule(str(rules_dir), 'rule-a', ['aegis_core/*'])

        report = generate_ci_report(
            workspace=str(tmp_path),
            changed_files=['aegis_core/metrics.py'],
            test_passed=True,
        )

        assert report['matched_rules'][0]['proposed_signal'] == 'trigger'

    def test_fail_generates_fp_signals(self, tmp_path):
        """When tests fail, matched rules get signal='fp'."""
        from aegis_core.enforcement import generate_ci_report

        rules_dir = tmp_path / '.aegis' / 'rules' / 'invariants'
        _make_rule(str(rules_dir), 'rule-a', ['aegis_core/*'])

        report = generate_ci_report(
            workspace=str(tmp_path),
            changed_files=['aegis_core/metrics.py'],
            test_passed=False,
        )

        assert report['matched_rules'][0]['proposed_signal'] == 'fp'



class TestMarkdownReport:
    """The markdown summary uses Aegis branding and rule table headers."""

    def test_report_markdown_format_uses_aegis_rule_branding(self, tmp_path):
        """Markdown output contains Aegis header and Rule table column."""
        from aegis_core.enforcement import generate_ci_report

        rules_dir = tmp_path / '.aegis' / 'rules' / 'boundaries'
        _make_rule(str(rules_dir), 'boundary-core', ['aegis_core/*'], rule_type='boundary')

        report = generate_ci_report(
            workspace=str(tmp_path),
            changed_files=['aegis_core/metrics.py'],
            test_passed=True,
            commit_sha='abc123',
        )

        md = report['summary']
        assert '## 🛡️ Aegis CI Outcome Report' in md
        assert '**Rules matched**: 1' in md
        assert '| Rule | Type |' in md
        assert 'boundary-core' in md
        assert 'trigger' in md

    def test_report_includes_commit_sha(self, tmp_path):
        """Commit SHA appears in the report header."""
        from aegis_core.enforcement import generate_ci_report

        rules_dir = tmp_path / '.aegis' / 'rules' / 'invariants'
        _make_rule(str(rules_dir), 'rule-x', ['src/*'])

        report = generate_ci_report(
            workspace=str(tmp_path),
            changed_files=['src/main.py'],
            test_passed=True,
            commit_sha='deadbeef',
        )

        assert 'deadbeef' in report['summary']

    def test_empty_report_still_valid_markdown(self, tmp_path):
        """Report with no matches still produces valid Aegis markdown."""
        from aegis_core.enforcement import generate_ci_report

        rules_dir = tmp_path / '.aegis' / 'rules' / 'invariants'
        os.makedirs(str(rules_dir), exist_ok=True)

        report = generate_ci_report(
            workspace=str(tmp_path),
            changed_files=['unmatched/file.txt'],
            test_passed=True,
        )

        md = report['summary']
        assert '## 🛡️ Aegis CI Outcome Report' in md
        assert '**Rules matched**: 0' in md

    def test_cli_main_supports_skipped_and_cancelled(self, tmp_path, monkeypatch):
        """CLI main parser accepts skipped and cancelled outcomes without crashing."""
        from aegis_core.enforcement import main

        rules_dir = tmp_path / '.aegis' / 'rules' / 'invariants'
        _make_rule(str(rules_dir), 'rule-x', ['src/*'])

        for outcome in ['skipped', 'cancelled']:
            monkeypatch.setattr(
                'sys.argv',
                [
                    'enforcement.py',
                    '--changed-files',
                    'src/main.py',
                    '--test-result',
                    outcome,
                    '--workspace',
                    str(tmp_path),
                ],
            )
            main()


