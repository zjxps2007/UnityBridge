using System.Collections.Immutable;
using System.Reflection.Metadata;
using System.Reflection.PortableExecutable;
using Microsoft.CodeAnalysis;

namespace UnityBridge.Compiler;

// Cache owned metadata images, never file handles. Callers still validate every
// reference before using a cached compilation, even if its timestamp is unchanged.
internal sealed class MetadataReferenceCache(int capacity = 512)
{
    private readonly BoundedCache<MetadataReferenceEntry> entries = new(capacity, 256L * 1024 * 1024);

    public MetadataReferenceEntry Get(string referencePath, Guid expectedMvid)
    {
        var path = Path.GetFullPath(referencePath);
        var identity = (OperatingSystem.IsWindows() ? path.ToUpperInvariant() : path) + "|" + expectedMvid.ToString("N");
        if (entries.TryGet(identity, out var entry))
        {
            using var stream = File.Open(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
            using var pe = new PEReader(stream);
            ValidateMvid(pe, expectedMvid, path);
            return entry;
        }

        // Validate the exact image supplied to Roslyn: one read and one immutable
        // copy instead of a preliminary metadata read and two full image copies.
        var image = ImmutableArray.Create(File.ReadAllBytes(path));
        using (var pe = new PEReader(image))
            ValidateMvid(pe, expectedMvid, path);
        entry = new MetadataReferenceEntry(identity, MetadataReference.CreateFromImage(image, filePath: path), image.Length);
        entries.Add(identity, entry, entry.Weight);
        return entry;
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
