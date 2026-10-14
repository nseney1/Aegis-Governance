from pathlib import Path
"""TDD tests for aegis_sdk.telemetry — unified signal evidence writer.

Tests written BEFORE implementation (Red phase).
"""
import json
import os
import threading
import pytest


class TestAppendSignal:
    """append_signal() writes a single JSONL record to the evidence log."""

    def test_writes_jsonl_record(self, tmp_path):
        """A single append creates one valid JSON line."""
        from aegis_sdk.telemetry import append_signal

        workspace = str(tmp_path)
        append_signal(
            workspace=workspace,
            cell_name='trap-example',
            signal_type='tp',
            source='ci',
            metadata={'commit_sha': 'abc123'},
        )

        log_path = tmp_path / '.soma' / 'evidence' / 'signals.jsonl'
        assert log_path.exists(), f'Expected {log_path} to exist'

        lines = log_path.read_text(encoding='utf-8').strip().splitlines()
        assert len(lines) == 1

        record = json.loads(lines[0])
        assert record['cell'] == 'trap-example'
        assert record['signal'] == 'tp'
        assert record['source'] == 'ci'
        assert record['metadata']['commit_sha'] == 'abc123'
        assert 'timestamp' in record

    def test_appends_multiple_records(self, tmp_path):
        """Multiple calls append to the same file, not overwrite."""
        from aegis_sdk.telemetry import append_signal

        workspace = str(tmp_path)
        append_signal(workspace=workspace, cell_name='cell-a', signal_type='tp', source='ci')
        append_signal(workspace=workspace, cell_name='cell-b', signal_type='fp', source='session')

        log_path = tmp_path / '.soma' / 'evidence' / 'signals.jsonl'
        lines = log_path.read_text(encoding='utf-8').strip().splitlines()
        assert len(lines) == 2

        records = [json.loads(line) for line in lines]
        assert records[0]['cell'] == 'cell-a'
        assert records[1]['cell'] == 'cell-b'

    def test_creates_directories_if_missing(self, tmp_path):
        """Parent directories (.soma/evidence/) are created automatically."""
        from aegis_sdk.telemetry import append_signal

        workspace = str(tmp_path)
        # No .soma/evidence/ exists yet
        append_signal(workspace=workspace, cell_name='cell-x', signal_type='trigger', source='ci')

        log_path = tmp_path / '.soma' / 'evidence' / 'signals.jsonl'
        assert log_path.exists()


class TestSignalSchema:
    """Every record must conform to the canonical schema."""

    def test_required_fields_present(self, tmp_path):
        """Every signal record has: timestamp, cell, signal, source."""
        from aegis_sdk.telemetry import append_signal

        workspace = str(tmp_path)
        append_signal(workspace=workspace, cell_name='rule-1', signal_type='trigger', source='ci')

        log_path = tmp_path / '.soma' / 'evidence' / 'signals.jsonl'
        record = json.loads(log_path.read_text(encoding='utf-8').strip())

        required = {'timestamp', 'cell', 'signal', 'source'}
        assert required.issubset(record.keys()), f'Missing keys: {required - record.keys()}'

    def test_signal_type_validated(self, tmp_path):
        """Invalid signal types are rejected."""
        from aegis_sdk.telemetry import append_signal

        workspace = str(tmp_path)
        with pytest.raises(ValueError, match='signal_type'):
            append_signal(workspace=workspace, cell_name='rule-1', signal_type='invalid', source='ci')

    def test_source_validated(self, tmp_path):
        """Invalid source values are rejected."""
        from aegis_sdk.telemetry import append_signal

        workspace = str(tmp_path)
        with pytest.raises(ValueError, match='source'):
            append_signal(workspace=workspace, cell_name='rule-1', signal_type='tp', source='unknown_source')

    def test_metadata_is_optional(self, tmp_path):
        """Signals can be written without metadata."""
        from aegis_sdk.telemetry import append_signal

        workspace = str(tmp_path)
        append_signal(workspace=workspace, cell_name='rule-1', signal_type='tp', source='session')

        log_path = tmp_path / '.soma' / 'evidence' / 'signals.jsonl'
        record = json.loads(log_path.read_text(encoding='utf-8').strip())
        # metadata should be empty dict or absent, not an error
        assert record.get('metadata') is None or isinstance(record.get('metadata'), dict)


class TestConcurrentAppend:
    """File writes must be safe under concurrent access."""

    def test_concurrent_writes_no_data_loss(self, tmp_path):
        """10 concurrent threads each writing 10 signals = 100 total records."""
        from aegis_sdk.telemetry import append_signal

        workspace = str(tmp_path)
        n_threads = 10
        n_per_thread = 10

        def writer(thread_id):
            for i in range(n_per_thread):
                append_signal(
                    workspace=workspace,
                    cell_name=f'cell-t{thread_id}-{i}',
                    signal_type='trigger',
                    source='ci',
                )

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        log_path = tmp_path / '.soma' / 'evidence' / 'signals.jsonl'
        lines = log_path.read_text(encoding='utf-8').strip().splitlines()
        assert len(lines) == n_threads * n_per_thread, (
            f'Expected {n_threads * n_per_thread} records, got {len(lines)}'
        )

        # Every line must be valid JSON
        for i, line in enumerate(lines):
            try:
                json.loads(line)
            except json.JSONDecodeError:
                pytest.fail(f'Line {i} is not valid JSON: {line!r}')


# ── Idempotent event identity, evidence lock, generation fence ─────────

def _signals(tmp_path):
    log_path = tmp_path / '.soma' / 'evidence' / 'signals.jsonl'
    if not log_path.exists():
        return []
    return [json.loads(l) for l in log_path.read_text(encoding='utf-8').splitlines() if l.strip()]


class TestIdempotentEventIdentity:

    def test_returns_persisted_record(self, tmp_path):
        from aegis_sdk.telemetry import append_signal
        rec = append_signal(str(tmp_path), 'cell-a', 'tp', 'ci', metadata={'k': 'v'})
        assert isinstance(rec, dict)
        assert _signals(tmp_path) == [rec]

    def test_no_key_means_no_event_id(self, tmp_path):
        from aegis_sdk.telemetry import append_signal
        rec = append_signal(str(tmp_path), 'cell-a', 'tp', 'ci')
        assert 'event_id' not in rec
        assert 'payload_digest' not in rec
        append_signal(str(tmp_path), 'cell-a', 'tp', 'ci')
        assert len(_signals(tmp_path)) == 2  # no dedupe without a key

    def test_event_id_excludes_signal_type_and_metadata(self, tmp_path):
        import hashlib
        from aegis_sdk.telemetry import append_signal
        rec = append_signal(str(tmp_path), 'cell-a', 'tp', 'ci', metadata={'x': 1},
                            principal='p', idempotency_scope='s', idempotency_key='k')
        expected = hashlib.sha256(b'p:s:k:cell-a').hexdigest()
        assert rec['event_id'] == expected
        assert len(rec['payload_digest']) == 64

    def test_payload_digest_is_canonical_and_excludes_timestamp(self, tmp_path):
        import hashlib
        from aegis_sdk.telemetry import append_signal
        rec = append_signal(str(tmp_path), 'cell-a', 'tp', 'ci', metadata={'b': 2, 'a': 1},
                            idempotency_key='k')
        canonical = json.dumps({'cell': 'cell-a', 'signal': 'tp', 'source': 'ci',
                                'metadata': {'a': 1, 'b': 2}},
                               sort_keys=True, separators=(',', ':'))
        assert rec['payload_digest'] == hashlib.sha256(canonical.encode('utf-8')).hexdigest()

    def test_same_key_same_payload_is_noop(self, tmp_path):
        from aegis_sdk.telemetry import append_signal
        first = append_signal(str(tmp_path), 'cell-a', 'tp', 'ci', metadata={'a': 1},
                              idempotency_scope='run-1', idempotency_key='op-1')
        log_path = tmp_path / '.soma' / 'evidence' / 'signals.jsonl'
        before = log_path.read_bytes()
        again = append_signal(str(tmp_path), 'cell-a', 'tp', 'ci', metadata={'a': 1},
                              idempotency_scope='run-1', idempotency_key='op-1')
        assert again == first
        assert log_path.read_bytes() == before

    def test_same_key_different_signal_conflicts(self, tmp_path):
        from aegis_sdk.telemetry import append_signal, EventConflictError
        append_signal(str(tmp_path), 'cell-a', 'tp', 'ci', idempotency_key='op-1')
        log_path = tmp_path / '.soma' / 'evidence' / 'signals.jsonl'
        before = log_path.read_bytes()
        with pytest.raises(EventConflictError):
            append_signal(str(tmp_path), 'cell-a', 'fp', 'ci', idempotency_key='op-1')
        assert log_path.read_bytes() == before
        assert issubclass(EventConflictError, ValueError)

    def test_same_key_different_metadata_conflicts(self, tmp_path):
        from aegis_sdk.telemetry import append_signal, EventConflictError
        append_signal(str(tmp_path), 'cell-a', 'tp', 'ci', metadata={'a': 1}, idempotency_key='op-1')
        with pytest.raises(EventConflictError):
            append_signal(str(tmp_path), 'cell-a', 'tp', 'ci', metadata={'a': 2}, idempotency_key='op-1')
        assert len(_signals(tmp_path)) == 1

    def test_same_key_different_cell_is_distinct_event(self, tmp_path):
        from aegis_sdk.telemetry import append_signal
        a = append_signal(str(tmp_path), 'cell-a', 'trigger', 'session', idempotency_key='t-1')
        b = append_signal(str(tmp_path), 'cell-b', 'trigger', 'session', idempotency_key='t-1')
        assert a['event_id'] != b['event_id']
        assert len(_signals(tmp_path)) == 2

    def test_concurrent_same_key_writes_exactly_once(self, tmp_path):
        from aegis_sdk.telemetry import append_signal
        errors = []

        def writer():
            try:
                append_signal(str(tmp_path), 'cell-a', 'tp', 'ci', idempotency_key='race')
            except Exception as exc:  # pragma: no cover - surfaced below
                errors.append(exc)

        threads = [threading.Thread(target=writer) for _ in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        assert len(_signals(tmp_path)) == 1


class TestEvidenceLock:

    def test_lock_file_location(self, tmp_path):
        from aegis_sdk.telemetry import evidence_lock
        with evidence_lock(str(tmp_path)):
            assert (tmp_path / '.soma' / 'evidence' / '.signals.lock').exists()

    def test_append_waits_for_lock_holder(self, tmp_path):
        import time
        from aegis_sdk.telemetry import append_signal, evidence_lock
        done = threading.Event()

        def writer():
            append_signal(str(tmp_path), 'cell-a', 'tp', 'ci')
            done.set()

        with evidence_lock(str(tmp_path)):
            t = threading.Thread(target=writer)
            t.start()
            time.sleep(0.3)
            assert not done.is_set(), 'append_signal must block while the evidence lock is held'
        t.join(5)
        assert done.is_set()
        assert len(_signals(tmp_path)) == 1


def _repo_ignores(rel_path):
    """True if the Soma checkout's ignore rules match rel_path (BUG-040)."""
    import shutil
    import subprocess
    repo = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
    if shutil.which('git') is None or not os.path.exists(os.path.join(repo, '.git')):
        pytest.skip('needs a git checkout of the repository')
    # --no-index checks the rules even for tracked paths, so an over-broad
    # pattern can't hide behind a file already being in the index.
    result = subprocess.run(
        ['git', '-C', repo, 'check-ignore', '-q', '--no-index', rel_path],
        capture_output=True, text=True)
    assert result.returncode in (0, 1), result.stderr
    return result.returncode == 0


class TestEvidenceLockIgnoredByGit:
    """BUG-040: the lock file evidence_lock() leaves behind must not show up as untracked."""

    def test_lock_file_is_ignored(self, tmp_path):
        from aegis_sdk.telemetry import evidence_lock
        with evidence_lock(str(tmp_path)) as lock_path:
            rel = os.path.relpath(lock_path, str(tmp_path)).replace(os.sep, '/')
        assert _repo_ignores(rel), f'{rel} is not git-ignored'

    @pytest.mark.parametrize('rel', [
        '.soma/evidence/outcomes.jsonl',
        '.soma/evidence/README.md',
        '.soma/evidence/arbitration_cycle_2.json',
        '.soma/evidence/.fitness.lock',
    ])
    def test_tracked_evidence_is_not_ignored(self, rel):
        assert not _repo_ignores(rel), f'{rel} must stay committable'


class TestGenerationFence:

    def test_default_generation_is_one(self, tmp_path):
        from aegis_sdk.telemetry import append_signal
        rec = append_signal(str(tmp_path), 'cell-a', 'tp', 'ci')
        assert rec['generation'] == 1

    def test_invalid_generation_file_defaults_to_one(self, tmp_path):
        from aegis_sdk.telemetry import append_signal
        (tmp_path / '.soma').mkdir()
        (tmp_path / '.soma' / 'epoch_generation').write_text('garbage')
        assert append_signal(str(tmp_path), 'cell-a', 'tp', 'ci')['generation'] == 1

    def test_generation_read_from_file(self, tmp_path):
        from aegis_sdk.telemetry import append_signal
        (tmp_path / '.soma').mkdir()
        (tmp_path / '.soma' / 'epoch_generation').write_text('3\n')
        rec = append_signal(str(tmp_path), 'cell-a', 'tp', 'ci', expected_generation=3)
        assert rec['generation'] == 3

    def test_stale_generation_rejected_without_write(self, tmp_path):
        from aegis_sdk.telemetry import append_signal, StaleGenerationError
        (tmp_path / '.soma').mkdir()
        (tmp_path / '.soma' / 'epoch_generation').write_text('2')
        with pytest.raises(StaleGenerationError):
            append_signal(str(tmp_path), 'cell-a', 'tp', 'ci', expected_generation=1)
        assert _signals(tmp_path) == []
        assert issubclass(StaleGenerationError, RuntimeError)

    def test_migration_lock_still_blocks(self, tmp_path):
        from aegis_sdk.telemetry import append_signal
        (tmp_path / '.soma').mkdir()
        (tmp_path / '.soma' / 'migration.lock').touch()
        with pytest.raises(RuntimeError, match='migration in progress'):
            append_signal(str(tmp_path), 'cell-a', 'tp', 'ci')
        assert _signals(tmp_path) == []
# ── Core Telemetry Consolidated Unit Tests (Phase 5) ─────────────────────

from aegis_core.telemetry import (
    append_signal as core_append_signal,
    read_signals as core_read_signals,
    current_generation as core_current_generation,
    increment_generation as core_increment_generation,
    detect_test_runner,
    letter_grade,
    compute_credit_weights,
    evaluate_quorum,
)


def test_telemetry_append_and_read_signals(tmp_path):
    ws = str(tmp_path)
    rec = core_append_signal(ws, "cell-1", "tp", "ci", metadata={"test": True})
    assert rec["cell"] == "cell-1"
    assert rec["signal"] == "tp"

    signals = core_read_signals(ws)
    assert len(signals) == 1
    assert signals[0]["cell"] == "cell-1"


def test_telemetry_generation_increment(tmp_path):
    ws = str(tmp_path)
    assert core_current_generation(ws) == 1
    gen = core_increment_generation(ws)
    assert gen == 2
    assert core_current_generation(ws) == 2


def test_telemetry_letter_grade():
    assert letter_grade(98) == "A+"
    assert letter_grade(85) == "B"
    assert letter_grade(50) == "F"


def test_telemetry_credit_weights():
    cells = [
        {"id": "cell-a", "target_paths": ["src/*.py"]},
        {"id": "cell-b", "target_paths": ["tests/*.py"]},
    ]
    weights = compute_credit_weights(cells, ["src/app.py"])
    assert weights["cell-a"] == 1.0
    assert weights["cell-b"] == 0.0


def test_evidence_lock_reentrancy(tmp_path):
    """C-02: evidence_lock must allow reentrant acquisition in the same thread without deadlock."""
    from aegis_core.telemetry import evidence_lock, increment_generation
    ws = str(tmp_path)
    with evidence_lock(ws):
        gen1 = increment_generation(ws)
        assert gen1 == 2
        with evidence_lock(ws):
            gen2 = increment_generation(ws)
            assert gen2 == 3


def test_telemetry_surrogate_characters(tmp_path):
    """C9: Telemetry must handle surrogate code points without UnicodeEncodeError."""
    from aegis_core.telemetry import append_signal, read_signals, compute_payload_digest
    ws = str(tmp_path)
    surrogate_text = "test-surrogate-\ud800-log"
    digest = compute_payload_digest("cell-1", "tp", "manual", metadata={"note": surrogate_text})
    assert isinstance(digest, str) and len(digest) == 64

    event = append_signal(
        workspace=ws,
        cell_name="cell-1",
        signal_type="tp",
        source="manual",
        metadata={"note": surrogate_text},
        idempotency_key="key-1",
    )
    assert event["payload_digest"] == digest

    signals = read_signals(ws)
    assert len(signals) == 1
    assert signals[0]["metadata"]["note"] == surrogate_text

