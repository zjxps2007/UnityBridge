using System.Reflection.Metadata;
using System.Reflection.PortableExecutable;
using System.Runtime.ExceptionServices;
using System.Runtime.InteropServices;
using Microsoft.CodeAnalysis;

namespace UnityBridge.Compiler;

// Cache owned metadata images, never file handles. Callers still validate every
// reference before using a cached compilation, even if its timestamp is unchanged.
internal sealed class MetadataReferenceCache(int capacity = 512)
{
    private readonly BoundedCache<MetadataReferenceEntry> entries = new(capacity, 256L * 1024 * 1024);

    public MetadataReferenceEntry Get(string referencePath, Guid expectedMvid)
        => GetMany([new ReferenceIdentity(referencePath, expectedMvid.ToString("D"))], 1)[0];

    public MetadataReferenceEntry[] GetMany(IReadOnlyList<ReferenceIdentity> inputs, int parallelism)
    {
        var work = new ReferenceWork[inputs.Count];
        // The LRU belongs to this thread. Independent file reads and immutable
        // image creation are the only operations allowed on parallel workers.
        for (var i = 0; i < inputs.Count; i++)
        {
            var item = work[i] = new ReferenceWork();
            try
            {
                var input = inputs[i];
                if (input is null || string.IsNullOrEmpty(input.Path) || !Guid.TryParse(input.Mvid, out item.Mvid))
                    throw new InvalidReferenceException("Each Unity reference requires a path and valid MVID.");
                if (!Path.IsPathFullyQualified(input.Path))
                    throw new InvalidReferenceException("Unity reference paths must be absolute.");
                item.Path = Path.GetFullPath(input.Path);
                item.Identity = (OperatingSystem.IsWindows() ? item.Path.ToUpperInvariant() : item.Path) + "|" + item.Mvid.ToString("N");
                entries.TryGet(item.Identity, out item.Entry);
                item.Cached = item.Entry is not null;
            }
            catch (Exception ex) { item.Error = ExceptionDispatchInfo.Capture(ex); }
        }

        if (parallelism > 1 && work.Length > 1)
            Parallel.ForEach(work, new ParallelOptions { MaxDegreeOfParallelism = Math.Min(4, parallelism) }, Load);
        else foreach (var item in work) Load(item);

        var result = new MetadataReferenceEntry[work.Length];
        for (var i = 0; i < work.Length; i++)
        {
            var item = work[i];
            // Report the first failing input, regardless of thread completion order.
            item.Error?.Throw();
            var entry = item.Entry!;
            if (!item.Cached) entries.Add(item.Identity, entry, entry.Weight);
            result[i] = entry;
        }
        return result;
    }

    private static void Load(ReferenceWork item)
    {
        if (item.Error is not null) return;
        try
        {
            if (item.Cached)
            {
                using var stream = File.Open(item.Path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
                using var pe = new PEReader(stream);
                ValidateMvid(pe, item.Mvid, item.Path);
            }
            else
            {
                // This newly allocated array has one owner and is never mutated or
                // exposed. Wrap it without making a second whole-file copy.
                var image = ImmutableCollectionsMarshal.AsImmutableArray(File.ReadAllBytes(item.Path));
                using (var pe = new PEReader(image)) ValidateMvid(pe, item.Mvid, item.Path);
                item.Entry = new MetadataReferenceEntry(item.Identity,
                    MetadataReference.CreateFromImage(image, filePath: item.Path), image.Length);
            }
        }
        catch (Exception ex) { item.Error = ExceptionDispatchInfo.Capture(ex); }
    }

    private sealed class ReferenceWork
    {
        public string Path = "";
        public string Identity = "";
        public Guid Mvid;
        public MetadataReferenceEntry? Entry;
        public bool Cached;
        public ExceptionDispatchInfo? Error;
    }

    private static void ValidateMvid(PEReader pe, Guid expectedMvid, string path)
    {
        if (!pe.HasMetadata)
            throw new StaleReferenceException("Unity reference changed: " + path);
        var metadata = pe.GetMetadataReader();
        if (metadata.GetGuid(metadata.GetModuleDefinition().Mvid) != expectedMvid)
            throw new StaleReferenceException("Unity reference changed: " + path);
    }
}

internal sealed record MetadataReferenceEntry(string Identity, PortableExecutableReference Reference, long Weight)
{
    // Reloading an evicted image allocates different bytes even if path/MVID match.
    // Old compilations may still own the earlier image; charge both allocations.
    public string RetentionId { get; } = Guid.NewGuid().ToString("N");
}

internal sealed class StaleReferenceException(string message) : Exception(message);
internal sealed class InvalidReferenceException(string message) : Exception(message);
