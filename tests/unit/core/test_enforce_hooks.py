"""Behavioral tests for pre-commit hook generation in cell_enforce.py.

Verifies the generated bash hooks correctly block/allow commits
based on file path pattern matching.
"""
import os
import stat
import subprocess
import tempfile
import textwrap

import pytest

import sys


def _create_git_repo_with_hook(hook_script: str) -> str:
    """Create a temp git repo with the given pre-commit hook.
    
    Returns the path to the repo.
    """
    repo = tempfile.mkdtemp()
    subprocess.run(['git', 'init', repo], capture_output=True, check=True)
    subprocess.run(['git', 'config', 'user.email', 'test@test.com'], capture_output=True, cwd=repo)
    subprocess.run(['git', 'config', 'user.name', 'Test'], capture_output=True, cwd=repo)
    
    # Create initial commit so HEAD exists
    init_file = os.path.join(repo, '.gitkeep')
    open(init_file, 'w').close()
    subprocess.run(['git', 'add', '.'], capture_output=True, cwd=repo)
    subprocess.run(['git', 'commit', '-m', 'init'], capture_output=True, cwd=repo)
    
    # Install hook
    hook_path = os.path.join(repo, '.git', 'hooks', 'pre-commit')
    # LF and UTF-8: Windows text mode would write CRLF (which bash rejects)
    # and encode with the locale codec.
    with open(hook_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(hook_script)
    os.chmod(hook_path, os.stat(hook_path).st_mode | stat.S_IEXEC)
    
    return repo


def _attempt_commit(repo: str, filename: str, content: str = 'test') -> subprocess.CompletedProcess:
    """Stage a file and attempt to commit. Returns the process result."""
    filepath = os.path.join(repo, filename)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w') as f:
        f.write(content)
    subprocess.run(['git', 'add', filename], capture_output=True, cwd=repo)
    return subprocess.run(
        ['git', 'commit', '-m', 'test commit'],
        capture_output=True, cwd=repo, text=True, encoding='utf-8', errors='replace'
    )


class TestWallHookGeneration:
    """Test wall-type cell hook generation."""
    
    def _get_wall_hook(self, name='test-wall', target_paths=None, hypothesis='Test hypothesis'):
        """Generate a wall hook script using cell_enforce."""
        from aegis_core.enforcement import generate_precommit_check
        cell = {
            '_name': name,
            'type': 'wall',
            'hypothesis': hypothesis,
            'target_paths': target_paths or ['src/*.py'],
            'enforcement': 'mechanical',
        }
        return generate_precommit_check(cell, '/tmp/test-workspace')
    
    def test_wall_hook_blocks_matching_commit(self):
        """A wall hook MUST block (exit 1) when staged files match target patterns."""
        hook = self._get_wall_hook(target_paths=['src/*.py'])
        repo = _create_git_repo_with_hook(hook)
        result = _attempt_commit(repo, 'src/app.py')
        assert result.returncode != 0, "Hook should block commits matching target patterns"
    
    def test_wall_hook_allows_unmatched_commit(self):
        """A wall hook MUST allow (exit 0) commits NOT matching target patterns."""
        hook = self._get_wall_hook(target_paths=['src/*.py'])
        repo = _create_git_repo_with_hook(hook)
        result = _attempt_commit(repo, 'docs/readme.txt')
        assert result.returncode == 0, "Hook should allow commits not matching target patterns"
    
    def test_wall_hook_empty_changed_files(self):
        """A wall hook MUST allow (exit 0) when no files are staged."""
        hook = self._get_wall_hook(target_paths=['src/*.py'])
        repo = _create_git_repo_with_hook(hook)
        # Attempt commit with nothing staged (should fail with empty commit, not hook)
        result = subprocess.run(
            ['git', 'commit', '--allow-empty', '-m', 'empty'],
            capture_output=True, cwd=repo, text=True, encoding='utf-8', errors='replace'
        )
        # --allow-empty bypasses changed-file check, so hook sees empty CHANGED_FILES
        # Our hook should exit 0 for empty files
        assert result.returncode == 0, "Hook should allow empty commits"
    
    def test_wall_hook_multiple_target_patterns(self):
        """A wall hook with multiple patterns blocks matching ANY pattern."""
        hook = self._get_wall_hook(target_paths=['src/*.py', 'lib/*.js'])
        repo = _create_git_repo_with_hook(hook)
        # Match second pattern
        result = _attempt_commit(repo, 'lib/app.js')
        assert result.returncode != 0, "Hook should block commits matching any target pattern"


class TestMembraneHookGeneration:
    """Test membrane-type cell hook generation."""
    
    def _get_membrane_hook(self, name='test-membrane', target_paths=None):
        from aegis_core.enforcement import generate_precommit_check
        cell = {
            '_name': name,
            'type': 'membrane',
            'hypothesis': 'Test membrane',
            'target_paths': target_paths or ['api/*.py'],
            'enforcement': 'mechanical',
        }
        return generate_precommit_check(cell, '/tmp/test-workspace')
    
    def test_membrane_hook_blocks_matching_commit(self):
        hook = self._get_membrane_hook(target_paths=['api/*.py'])
        repo = _create_git_repo_with_hook(hook)
        result = _attempt_commit(repo, 'api/handler.py')
        assert result.returncode != 0, "Membrane hook should block matching commits"
    
    def test_membrane_hook_allows_unmatched_commit(self):
        hook = self._get_membrane_hook(target_paths=['api/*.py'])
        repo = _create_git_repo_with_hook(hook)
        result = _attempt_commit(repo, 'docs/guide.md')
        assert result.returncode == 0, "Membrane hook should allow non-matching commits"


class TestVacuoleHookGeneration:
    """Test vacuole-type (default) cell hook generation."""
    
    def _get_vacuole_hook(self, name='test-vacuole', target_paths=None):
        from aegis_core.enforcement import generate_precommit_check
        cell = {
            '_name': name,
            'type': 'vacuole',
            'hypothesis': 'Test vacuole',
            'target_paths': target_paths or ['data/*.csv'],
            'enforcement': 'mechanical',
        }
        return generate_precommit_check(cell, '/tmp/test-workspace')
    
    def test_vacuole_hook_blocks_matching_commit(self):
        hook = self._get_vacuole_hook(target_paths=['data/*.csv'])
        repo = _create_git_repo_with_hook(hook)
        result = _attempt_commit(repo, 'data/users.csv')
        assert result.returncode != 0, "Vacuole hook should block matching commits"
    
    def test_vacuole_hook_allows_unmatched_commit(self):
        hook = self._get_vacuole_hook(target_paths=['data/*.csv'])
        repo = _create_git_repo_with_hook(hook)
        result = _attempt_commit(repo, 'src/main.py')
        assert result.returncode == 0, "Vacuole hook should allow non-matching commits"
