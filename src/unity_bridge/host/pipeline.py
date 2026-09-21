"""Optional asynchronous receipts over the existing authenticated host transport."""
from __future__ import annotations

from dataclasses import dataclass
import time
import uuid

from . import _endpoint
from .registry import normalized_project
from .results import not_started, unknown
from .transport import TransportError, post
from ..client import CommandResponse
from .._timing import mark


@dataclass
class Ticket:
    connection: PipelineConnection
    payload: dict
    deadline: float
    response: CommandResponse | None = None

    def wait(self) -> CommandResponse:
        if self.response is not None:
            return self.response
        try:
            # A receipt may be read just after expiry; this grace does not extend
            # execution, whose original deadline is owned by the host Job.
            result = self.connection.exchange('/result', self.payload, max(.1, self.deadline - time.perf_counter() + .1), 'results')
            if not isinstance(result.get('success'), bool) or not isinstance(result.get('message'), str):
                raise TransportError('Invalid pipeline receipt')
            return CommandResponse.from_dict(result)
        except TransportError:
            return CommandResponse.from_dict(unknown('exec'))


class PipelineConnection:
    def __init__(self, descriptor, endpoint, target, pool):
        self.descriptor, self.endpoint, self.target, self.pool = descriptor, endpoint, target, pool
        self.key = (normalized_project(target.project_path), target.pid)
        self.identity = (endpoint['pid'], descriptor['runtimeId'], target.pid,
                         target.port, target.domain_id, target.reference_generation)

    @classmethod
    def discover(cls, client, pool):
        if client.backend == 'legacy':
            return None
        target = client.discover_instance()
        if target.bridge_protocol != 1:
            return None
        descriptor, endpoint, registered = _endpoint(target, client.instances_dir)
        if not registered or endpoint is None or endpoint.get('pipelineProtocol') != 1:
            return None  # No command has been transmitted; sequential fallback is safe.
        return cls(descriptor, endpoint, target, pool)

    def exchange(self, path, payload, timeout, lane):
        # The coordinator serializes enqueue and ordinary barrier commands. Use
        # their shared execution connection so the first barrier does not revive
        # an idle socket; receipts and cancellation still have separate lanes.
        key = (self.key[0], 'execute') if lane == 'enqueue' else (self.key, 'pipeline-' + lane)
        return post(self.endpoint['port'], self.descriptor['token'], path, payload, timeout,
                    pool=self.pool, key=key, identity=self.identity)

    def enqueue(self, params, pipeline_id, timeout_ms, parent_request_id=None, *, deadline=None):
        deadline = deadline if deadline is not None else time.perf_counter() + timeout_ms / 1000
        remaining = deadline - time.perf_counter()
        request_id = uuid.uuid4().hex
        target = {'projectPath': self.target.project_path, 'pid': self.target.pid, 'port': self.target.port}
        receipt = {'request_id': request_id, 'pipeline_id': pipeline_id, 'target': target}
        ticket = Ticket(self, receipt, deadline)
        if remaining <= 0:
            ticket.response = CommandResponse.from_dict(not_started('expired', 'Request expired before submission'))
            return ticket
        payload = dict(receipt, command='exec', params=params, deadline_unix_ms=int(time.time() * 1000 + remaining * 1000),
                       parent_request_id=parent_request_id)
        mark('client_enqueue', request_id, parent_request_id=parent_request_id)
        try:
            result = self.exchange('/enqueue', payload, remaining, 'enqueue')
            if result.get('accepted') is False and isinstance(result.get('response'), dict):
                response = result['response']
                if not isinstance(response.get('success'), bool) or not isinstance(response.get('message'), str):
                    raise TransportError('Invalid enqueue rejection')
                ticket.response = CommandResponse.from_dict(response)
            elif result.get('accepted') is not True or result.get('request_id') != request_id:
                raise TransportError('Invalid enqueue receipt')
        except TransportError:
            ticket.response = CommandResponse.from_dict(unknown('exec'))
        return ticket

    def cancel(self, pipeline_id):
        try:
            self.exchange('/cancel', {'pipeline_id': pipeline_id,
                                      'target': {'projectPath': self.target.project_path, 'pid': self.target.pid}}, 1., 'cancel')
        except TransportError:
            pass  # Cancellation never authorizes a retry of an execution request.
