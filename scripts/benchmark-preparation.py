"""Isolate compiler preparation; emits bytes but never executes Unity code."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from unity_bridge.host.compiler import CompilerWorker


def stats(values):
    values = sorted(values)
    return {'n': len(values), 'p50_ms': values[math.ceil(len(values) * .5) - 1],
            'p95_ms': values[math.ceil(len(values) * .95) - 1]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context', type=Path, required=True)
    parser.add_argument('--worker', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--samples', type=int, default=50)
    parser.add_argument('--warm-samples', type=int, default=100)
    args = parser.parse_args()
    if args.output.exists(): parser.error('Use a new output file to preserve evidence')
    context = json.loads(args.context.read_text(encoding='utf-8'))
    payload = {'operation': 'compile', 'code': 'return 42;', 'usings': [],
               'language_version': context['languageVersion'], 'references': context['references'],
               'project_id': 'preparation-benchmark', 'reference_generation': 'fixed-context', 'fresh_identity': True}
    rows = []
    output = {'scope': 'Compiler only, OS cache retained, no Unity execution', 'rows': rows}
    original = os.environ.get('UNITY_BRIDGE_DISABLE_BASE_COMPILATION')
    original_enable = os.environ.get('UNITY_BRIDGE_ENABLE_BASE_COMPILATION')
    try:
        for sample in range(args.samples):
            order = ['no_base', 'base', 'bootstrap']
            if sample % 2: order.reverse()
            for variant in order:
                os.environ['UNITY_BRIDGE_DISABLE_BASE_COMPILATION'] = '1' if variant == 'no_base' else '0'
                os.environ['UNITY_BRIDGE_ENABLE_BASE_COMPILATION'] = '0' if variant == 'no_base' else '1'
                worker = CompilerWorker(str(args.worker))
                try:
                    started = time.perf_counter()
                    if variant == 'bootstrap': worker.warmup()
                    else: worker.prewarm()
                    prepared = time.perf_counter()
                    result = worker.request(payload, deadline=time.perf_counter() + 30)
                    finished = time.perf_counter()
                    assert result['success'] and not result['emit_reused']
                    rows.append({'variant': variant, 'sample': sample, 'name': 'first',
                                 'prepare_ms': (prepared - started) * 1000,
                                 'compile_ms': (finished - prepared) * 1000, 'total_ms': (finished - started) * 1000})
                    if sample == 0:
                        names = set()
                        for index in range(args.warm_samples):
                            for repeated in (False, True):
                                request = dict(payload, code='return 42;' if repeated else f'return {index} + 1024;')
                                begin = time.perf_counter()
                                result = worker.request(request, deadline=time.perf_counter() + 30)
                                elapsed = (time.perf_counter() - begin) * 1000
                                assert not result['emit_reused'] and result['assembly_name'] not in names
                                names.add(result['assembly_name'])
                                rows.append({'variant': variant, 'name': 'repeat' if repeated else 'new',
                                             'sample': index, 'total_ms': elapsed, 'base_cache_hit': result.get('base_cache_hit')})
                finally:
                    worker.close()
            args.output.write_text(json.dumps(output, indent=2), encoding='utf-8')
    finally:
        if original is None: os.environ.pop('UNITY_BRIDGE_DISABLE_BASE_COMPILATION', None)
        else: os.environ['UNITY_BRIDGE_DISABLE_BASE_COMPILATION'] = original
        if original_enable is None: os.environ.pop('UNITY_BRIDGE_ENABLE_BASE_COMPILATION', None)
        else: os.environ['UNITY_BRIDGE_ENABLE_BASE_COMPILATION'] = original_enable
    output['summary'] = {variant: {name: {metric: stats([r[metric] for r in rows if r['variant'] == variant and r['name'] == name])
        for metric in (('prepare_ms', 'compile_ms', 'total_ms') if name == 'first' else ('total_ms',))}
        for name in ('first', 'new', 'repeat')} for variant in ('no_base', 'base', 'bootstrap')}
    args.output.write_text(json.dumps(output, indent=2), encoding='utf-8')
    print(json.dumps(output['summary'], indent=2))


if __name__ == '__main__':
    main()
