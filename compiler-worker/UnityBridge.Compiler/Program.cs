using System.Text;
using System.Text.Json;

namespace UnityBridge.Compiler;

public static class Program
{
    public static async Task Main()
    {
        Console.InputEncoding = new UTF8Encoding(false);
        Console.OutputEncoding = new UTF8Encoding(false);
        await ServeAsync(Console.In, Console.Out);
    }

    public static async Task ServeAsync(TextReader input, TextWriter output)
    {
        var engine = new CompilerEngine();
        while (await input.ReadLineAsync() is { } line)
        {
            CompileResponse response;
            try
            {
                if (line.Length > 16 * 1024 * 1024)
                    throw new JsonException("Compiler request exceeds 16 MiB.");
                var request = JsonSerializer.Deserialize<CompileRequest>(line, WireJson.Options)
                    ?? throw new JsonException("Compiler request must be an object.");
                response = engine.Process(request);
            }
            catch (JsonException ex)
            {
                response = new CompileResponse
                {
                    Success = false, ErrorCode = "invalid_request", Error = ex.Message,
                };
            }
            await output.WriteLineAsync(JsonSerializer.Serialize(response, WireJson.Options));
            await output.FlushAsync();
        }
    }
}
