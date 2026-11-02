"""Isolate native inference/encoding from the HTTP process, using JSON only.

One child per queued production job, same interpreter/environment, local stdin
request and a small private receipt. No pickle, shell, cloud, or new dependency.
"""
from __future__ import annotations
import json
from pathlib import Path
import subprocess
import sys
import tempfile

_CODES = frozenset({'analysis_failed', 'invalid_media',
    'selected_crew_lost_or_ambiguous', 'analysis_process_failed', 'analysis_timeout'})
MAX_RECEIPT_BYTES = 16384


class AnalysisProcessError(RuntimeError):
    def __init__(self, code='analysis_process_failed'):
        self.code = code if code in _CODES else 'analysis_process_failed'
        super().__init__(self.code)


def _command(receipt):
    return [sys.executable, '-u', '-X', 'faulthandler', '-m',
            'strokesense.analysis_worker', str(receipt)]


def run_isolated(video, *, out_dir, selection=None, timeout=3600):
    """A child exit cannot kill the server; timeout is an upper runtime bound."""
    root = Path(out_dir).resolve()
    with tempfile.TemporaryDirectory(prefix='.worker-', dir=root) as tmp:
        receipt = Path(tmp) / 'result.json'
        request = json.dumps({'video': str(Path(video).resolve()), 'out_dir': str(root),
                              'selection': selection}, allow_nan=False)
        try:
            completed = subprocess.run(_command(receipt), input=request, text=True,
                encoding='utf-8', cwd=str(Path(__file__).resolve().parents[1]), timeout=timeout)
        except subprocess.TimeoutExpired:
            print('StrokeSense analysis worker timed out.', file=sys.stderr, flush=True)
            raise AnalysisProcessError('analysis_timeout') from None
        except OSError:
            raise AnalysisProcessError() from None
        if completed.returncode != 0:
            print(f'StrokeSense analysis worker exited: {completed.returncode}',
                  file=sys.stderr, flush=True)
            raise AnalysisProcessError()
        try:
            with receipt.open('rb') as stream:
                data = stream.read(MAX_RECEIPT_BYTES + 1)
            if len(data) > MAX_RECEIPT_BYTES:
                raise ValueError('oversized_receipt')
            result = json.loads(data)
            if not isinstance(result, dict):
                raise ValueError('invalid_receipt')
            if result.get('state') == 'failed':
                raise AnalysisProcessError(result.get('code'))
            if result.get('state') == 'empty':
                return None
            if (set(result) != {'state', 'report', 'video'} or result['state'] != 'succeeded'
                    or not isinstance(result['report'], str)
                    or not isinstance(result['video'], (str, type(None)))):
                raise ValueError('invalid_receipt')
            # JobQueue separately enforces output containment, size and hashes.
            return {'report': Path(result['report']),
                    'video': Path(result['video']) if result['video'] else None}
        except (OSError, ValueError, TypeError, KeyError):
            raise AnalysisProcessError() from None


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        return 2
    receipt = Path(argv[0])
    result = {'state': 'failed', 'code': 'analysis_failed'}
    try:
        from .jobs import _default_analyze
        from .media import UndecodableMediaError
        from .selection import SelectionError
        request = json.loads(sys.stdin.read(16385))
        if set(request) != {'video', 'out_dir', 'selection'}:
            raise ValueError('invalid_request')
        try:
            analyzed = _default_analyze(Path(request['video']), out_dir=Path(request['out_dir']),
                                        selection=request['selection'])
            result = {'state': 'empty'} if analyzed is None else {
                'state': 'succeeded', 'report': str(analyzed['report']),
                'video': str(analyzed['video']) if analyzed.get('video') else None}
        except UndecodableMediaError:
            result['code'] = 'invalid_media'
        except SelectionError:
            result['code'] = 'selected_crew_lost_or_ambiguous'
    except Exception as exc:
        # Fixed categories only: exception text/custom names can contain private data.
        category = next((kind.__name__ for kind in
            (ValueError, TypeError, KeyError, IndexError, OSError, RuntimeError)
            if type(exc) is kind), 'Exception')
        # Native crashes cannot reach here; the parent observes their exit code.
        print(f'StrokeSense child analysis failed ({category}); no results released.',
              file=sys.stderr, flush=True)
    receipt.write_text(json.dumps(result, allow_nan=False), encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
