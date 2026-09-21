"""Bounded read-ahead for inline exec; a single coordinator parses and writes.

Only the input reader and receipt reader block in background threads. Execution
is ordered by the host, while ordinary commands and file reads are barriers.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import queue
import sys
import threading
import time
import uuid

from .commands import result_exit_code
from .output import to_jsonable
from .session import inherited_args, read_request, write_response
from .._timing import mark
from ..adapter import UnityActionResult, _compact, _list_or_csv
from ..client import CommandResponse, UnityBridgeError
from ..host.pipeline import PipelineConnection
from ..host.results import not_started, unknown


@dataclass
class Pending:
    user_id: object
    argv: list[str] | None
    error: str | None
    received: float
    trace_id: str = ''
    params: dict | None = None
    ticket: object = None


def action_response(params, response):
    result = UnityActionResult.from_response(tool='exec', command='exec', params=params, response=response)
    return result_exit_code(result), to_jsonable(result), None


def run_pipeline(args, executor):
    events, receipts = queue.Queue(), queue.Queue()
    permits = threading.BoundedSemaphore(args.pipeline)
    stopped = threading.Event()
    stream, output = sys.stdin, sys.stdout
    inherited = inherited_args(args)

    def read_input():
        try:
            while not stopped.is_set():
                permits.acquire()
                if stopped.is_set():
                    permits.release()
                    return
                request = read_request(stream)
                if request is None:
                    permits.release()
                    events.put(('eof', None))
                    return
                events.put(('input', Pending(*request, time.perf_counter())))
        except (OSError, ValueError) as exc:
            events.put(('input_error', exc))

    def read_receipts():
        while True:
            item = receipts.get()
            if item is None:
                return
            try:
                response = item.ticket.wait()
            except Exception:
                # A failure after submission can never authorize fallback/replay.
                response = CommandResponse.from_dict(unknown('exec'))
            events.put(('result', (item, response)))

    threading.Thread(target=read_input, name='unity-session-input', daemon=True).start()
    threading.Thread(target=read_receipts, name='unity-session-results', daemon=True).start()
    waiting, active = deque(), deque()
    connection, group = None, uuid.uuid4().hex
    eof, aborted = False, False

    def emit(item, value):
        write_response(output, item.user_id, *value)
        if item.trace_id:
            mark('session_request_end', item.trace_id)
        permits.release()

    def abort():
        nonlocal aborted
        if not aborted:
            aborted = True
            stopped.set()
            if connection is not None:
                connection.cancel(group)

    try:
        while True:
            # Process input only on the coordinator. Never share parser diagnostics
            # or stdout with either blocking reader.
            while waiting:
                item = waiting[0]
                if aborted:
                    if active:
                        break
                    waiting.popleft()
                    emit(item, (1, None, 'Pipeline stopped after an unconfirmed response; request was not submitted'))
                    continue
                candidate, parsed = None, None
                if item.error is None:
                    try:
                        parsed, direct = executor.parse(inherited + item.argv)
                        eligible = (not direct and parsed.command == 'exec' and parsed.code is not None
                                    and not parsed.csc and not parsed.dotnet)
                        if eligible:
                            from ..cli import _create_client
                            client = _create_client(parsed)
                            candidate = PipelineConnection.discover(client, executor.connection_pool())
                    except (SystemExit, UnityBridgeError, ValueError, TypeError):
                        pass  # A barrier below invokes the normal error path.
                if candidate is None or (active and (candidate.key != connection.key or candidate.identity != connection.identity)):
                    if active:
                        break
                    waiting.popleft()
                    if item.error is not None:
                        value = (2, None, item.error)
                    else:
                        value = executor.invoke(inherited + item.argv, request_id=item.user_id, received_at=item.received)
                    emit(item, value)
                    connection, group = None, uuid.uuid4().hex
                    continue
                if (not active and connection is not None
                        and (candidate.key != connection.key or candidate.identity != connection.identity)):
                    group = uuid.uuid4().hex
                connection = candidate
                waiting.popleft()
                item.params = _compact({'code': parsed.code, 'usings': _list_or_csv(parsed.usings)})
                item.trace_id = uuid.uuid4().hex
                mark('session_request_begin', item.trace_id, parent_request_id=item.user_id)
                item.ticket = connection.enqueue(item.params, group, parsed.timeout_ms,
                                                 parent_request_id=item.trace_id,
                                                 deadline=item.received + parsed.timeout_ms / 1000)
                active.append(item)
                if len(active) == 1:
                    receipts.put(item)
                if item.ticket.response is not None and item.ticket.response.completion_unknown:
                    abort()
                    break

            if not active and not waiting and (eof or aborted):
                # Drain inputs already read before abort, without waiting for an
                # interactive writer to close stdin after a lost response.
                if aborted:
                    while True:
                        try:
                            kind, value = events.get_nowait()
                        except queue.Empty:
                            break
                        if kind == 'input':
                            waiting.append(value)
                    if waiting:
                        continue
                return 1 if aborted else 0
            kind, value = events.get()
            if kind == 'input':
                waiting.append(value)
            elif kind == 'eof':
                eof = True
            elif kind == 'input_error':
                raise value
            elif kind == 'result':
                item, response = value
                assert active.popleft() is item
                if response.completion_unknown:
                    abort()
                emit(item, action_response(item.params, response))
                if active:
                    receipts.put(active[0])
    finally:
        stopped.set()
        if active and connection is not None:
            connection.cancel(group)
        receipts.put(None)
