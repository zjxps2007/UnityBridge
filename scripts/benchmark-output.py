"""Measure the removed session JSON round trip; not an end-to-end CLI benchmark."""
from __future__ import annotations

import argparse
from io import StringIO
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from unity_bridge._cli.output import print_result, to_jsonable
from unity_bridge.client import CommandResponse


def render(result, legacy):
    if legacy:
        output = StringIO()
        print_result(result, json_output=True, stdout=output)
        value = json.loads(output.getvalue())
    else:
        value = to_jsonable(result)
    return json.dumps({'id': 1, 'exit_code': 0, 'result': value, 'error': None},
                      ensure_ascii=False, separators=(',', ':'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--samples', type=int, default=100)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Use a new output file')
    results = {'scope': __doc__, 'python': sys.version, 'rows': [], 'summary': {}}
    for size, payload in [('small', {'entries': [{'message': 'example', 'type': 'log'}]}),
                          ('large_unicode', '\uac00' * (512 * 1024))]:
        result = CommandResponse(success=True, message='Result', data=payload)
        assert render(result, True) == render(result, False)
        for index in range(args.samples):
            for legacy in ([True, False] if index % 2 else [False, True]):
                started = time.perf_counter()
                rendered = render(result, legacy)
                elapsed = (time.perf_counter() - started) * 1000
                results['rows'].append({'size': size, 'legacy': legacy, 'sample': index, 'ms': elapsed})
        results['summary'][size] = {}
        for legacy in (True, False):
            samples = sorted(r['ms'] for r in results['rows'] if r['size'] == size and r['legacy'] == legacy)
            results['summary'][size]['legacy' if legacy else 'structured'] = {
                'n': len(samples), 'p50_ms': samples[math.ceil(.5 * len(samples)) - 1],
                'p95_ms': samples[math.ceil(.95 * len(samples)) - 1], 'output_chars': len(rendered)}
    args.output.write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(json.dumps(results['summary'], indent=2))


if __name__ == '__main__':
    main()
