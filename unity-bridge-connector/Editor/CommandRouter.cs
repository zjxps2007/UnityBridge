using System;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace UnityBridgeConnector
{
    /// <summary>
    /// Routes incoming command requests to the appropriate tool handler.
    /// Tool execution is serialized to prevent races between CLI agents.
    /// Readiness and compiler-context controls bypass that execution lock.
    /// </summary>
    public static class CommandRouter
    {
        static readonly SemaphoreSlim s_Lock = new SemaphoreSlim(1, 1);

        public static async Task<object> Dispatch(string command, JObject parameters)
        {
            return await Dispatch(command, parameters, null);
        }

        internal static async Task<object> Dispatch(string command, JObject parameters, BridgeRequestContext request)
        {
            var rejected = BridgeProtocol.Validate(request);
            if (rejected != null) return rejected;
            if (BridgeProtocol.IsInternalCommand(command) && (request == null || !request.Authenticated))
                return BridgeProtocol.Reject("unauthorized", "Host authentication required.");

            // These controls remain on the Editor thread, but do not wait behind
            // a long-running asynchronous tool or external compilation request.
            if (command == "get_editor_state")
                return await DispatchInternal(command, parameters);
            if (command == "bridge_context")
                return BridgeProtocol.CaptureContext();

            if (request?.DeadlineUnixMs != null)
            {
                var remaining = request.DeadlineUnixMs.Value - DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                if (remaining <= 0 || !await s_Lock.WaitAsync((int)Math.Min(remaining, int.MaxValue)))
                    return BridgeProtocol.Reject("expired", "Request deadline expired while waiting to execute.");
            }
            else await s_Lock.WaitAsync();
            try
            {
                // A timeout/domain change may occur while queued behind another tool.
                rejected = BridgeProtocol.Validate(request, request != null && request.Authenticated);
                if (rejected != null) return rejected;
                if (command == "bridge_exec_assembly")
                    return BridgeProtocol.ExecuteAssembly(parameters, request);
                return await DispatchInternal(command, parameters);
            }
            finally
            {
                s_Lock.Release();
            }
        }

        static async Task<object> DispatchInternal(string command, JObject parameters)
        {
            if (command == "list")
                return new SuccessResponse("Available tools", ToolDiscovery.GetToolSchemas());

            if (command == "get_editor_state")
                return new SuccessResponse("Current editor state", new
                {
                    requestId = parameters?["request_id"]?.ToString(),
                    instance = Heartbeat.CaptureState(),
                });

            var handler = ToolDiscovery.FindHandler(command);
            if (handler == null)
                return new ErrorResponse($"Unknown command: {command}");

            try
            {
                var result = handler.Invoke(null, new object[] { parameters ?? new JObject() });

                if (result is Task<object> asyncTask)
                    return await asyncTask;

                if (result is Task task)
                {
                    await task;
                    return new SuccessResponse($"{command} completed");
                }

                return result ?? new SuccessResponse($"{command} completed");
            }
            catch (Exception ex)
            {
                var inner = ex.InnerException ?? ex;
                Debug.LogException(inner);
                return new ErrorResponse($"{command} failed: {inner.Message}");
            }
        }
    }
}
