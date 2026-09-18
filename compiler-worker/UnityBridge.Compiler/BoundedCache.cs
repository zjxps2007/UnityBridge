namespace UnityBridge.Compiler;

internal sealed class BoundedCache<T>(int capacity, long maxBytes) where T : class
{
    private sealed record Entry(string Key, T Value, long Weight, KeyValuePair<string, long>[] Shared);
    private readonly Dictionary<string, LinkedListNode<Entry>> entries = new(StringComparer.Ordinal);
    private readonly LinkedList<Entry> lru = new();
    private readonly Dictionary<string, (long Weight, int Users)> shared = new(StringComparer.Ordinal);
    private long bytes;

    public bool TryGet(string key, out T value)
    {
        if (entries.TryGetValue(key, out var node))
        {
            lru.Remove(node);
            lru.AddLast(node);
            value = node.Value.Value;
            return true;
        }
        value = null!;
        return false;
    }

    public void Add(string key, T value, long weight, IEnumerable<KeyValuePair<string, long>>? sharedWeights = null)
    {
        // Compilation entries share immutable metadata images. Count each image
        // once while any retained compilation owns it, including after metadata
        // cache eviction. Independent syntax/emission weights remain per entry.
        var resources = (sharedWeights ?? []).GroupBy(item => item.Key, StringComparer.Ordinal)
            .Select(group => new KeyValuePair<string, long>(group.Key, group.Max(item => item.Value))).ToArray();
        if (entries.TryGetValue(key, out var existing)) Remove(existing);
        if (weight > maxBytes || resources.Sum(item => item.Value) > maxBytes - weight) return;
        long AdditionalWeight() => weight + resources.Sum(item => shared.TryGetValue(item.Key, out var current)
            ? Math.Max(0, item.Value - current.Weight) : item.Value);
        while (entries.Count >= capacity || bytes + AdditionalWeight() > maxBytes)
        {
            Remove(lru.First!);
        }
        foreach (var item in resources)
        {
            if (shared.TryGetValue(item.Key, out var current))
            {
                bytes += Math.Max(0, item.Value - current.Weight);
                shared[item.Key] = (Math.Max(current.Weight, item.Value), current.Users + 1);
            }
            else
            {
                shared[item.Key] = (item.Value, 1);
                bytes += item.Value;
            }
        }
        entries[key] = lru.AddLast(new Entry(key, value, weight, resources));
        bytes += weight;
    }

    private void Remove(LinkedListNode<Entry> node)
    {
        bytes -= node.Value.Weight;
        foreach (var item in node.Value.Shared)
        {
            var current = shared[item.Key];
            if (current.Users == 1)
            {
                bytes -= current.Weight;
                shared.Remove(item.Key);
            }
            else shared[item.Key] = (current.Weight, current.Users - 1);
        }
        entries.Remove(node.Value.Key);
        lru.Remove(node);
    }
}
