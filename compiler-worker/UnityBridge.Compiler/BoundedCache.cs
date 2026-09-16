namespace UnityBridge.Compiler;

internal sealed class BoundedCache<T>(int capacity, long maxBytes) where T : class
{
    private readonly Dictionary<string, LinkedListNode<(string Key, T Value, long Weight)>> entries = new(StringComparer.Ordinal);
    private readonly LinkedList<(string Key, T Value, long Weight)> lru = new();
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

    public void Add(string key, T value, long weight)
    {
        if (entries.Remove(key, out var existing))
        {
            bytes -= existing.Value.Weight;
            lru.Remove(existing);
        }
        if (weight > maxBytes) return;
        while (entries.Count >= capacity || bytes + weight > maxBytes)
        {
            var oldest = lru.First!;
            bytes -= oldest.Value.Weight;
            entries.Remove(oldest.Value.Key);
            lru.RemoveFirst();
        }
        entries[key] = lru.AddLast((key, value, weight));
        bytes += weight;
    }
}
