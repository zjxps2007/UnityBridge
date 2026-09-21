using System.Buffers.Binary;
using System.Collections.Immutable;
using System.Reflection.Metadata;
using System.Reflection.Metadata.Ecma335;
using System.Reflection.PortableExecutable;
using Microsoft.Win32.SafeHandles;

namespace UnityBridge.Compiler;

// Remember where a validated image stores its MVID, not the value of a later
// file. Every hit opens the current file and reads it again. If any structure
// used to locate the GUID changed, the caller falls back to a full PE reader.
internal sealed class ReferenceMvidProbe
{
    private const int MaxProbeBytes = 4096;
    private readonly long fileLength;
    private readonly Region[] layout;
    private readonly int mvidOffset;

    private ReferenceMvidProbe(int length, Region[] layout, int mvidOffset)
        => (fileLength, this.layout, this.mvidOffset) = (length, layout, mvidOffset);

    public int Weight => layout.Sum(region => region.Bytes.Length);

    public static ReferenceMvidProbe? Create(PEReader pe, ImmutableArray<byte> image)
    {
        var headers = pe.PEHeaders;
        var reader = pe.GetMetadataReader();
        var module = reader.GetModuleDefinition();
        var tableOffset = reader.GetTableMetadataOffset(TableIndex.Module);
        var prefixLength = tableOffset + reader.GetTableRowSize(TableIndex.Module);
        var headerLength = headers.PEHeader?.SizeOfHeaders ?? 0;
        var sectionTableEnd = headers.CoffHeaderStartOffset + 20 + headers.CoffHeader.SizeOfOptionalHeader
            + headers.SectionHeaders.Length * 40;
        if (module.Mvid.IsNil || headerLength <= 0 || headerLength > MaxProbeBytes
            || headerLength < sectionTableEnd || headerLength > image.Length
            || prefixLength <= 0 || prefixLength > MaxProbeBytes || headers.CorHeaderStartOffset < 0)
            return null;

        var metadata = image.AsSpan(headers.MetadataStartOffset, headers.MetadataSize);
        // A legal but unusual stream order can put a table before the end of
        // the stream directory. Only use the shortcut when the entire directory
        // is included in the immutable prefix we compare on every request.
        if (!ContainsStreamDirectory(metadata, tableOffset)) return null;
        var guidIndex = MetadataTokens.GetHeapOffset(module.Mvid); // One-based GUID index, not bytes.
        var guidOffset = checked(reader.GetHeapMetadataOffset(HeapIndex.Guid) + (guidIndex - 1) * 16);
        if (guidOffset < 0 || guidOffset > metadata.Length - 16) return null;
        return new ReferenceMvidProbe(image.Length,
            [new Region(0, image.AsSpan(0, headerLength).ToArray()),
             new Region(headers.CorHeaderStartOffset, image.AsSpan(headers.CorHeaderStartOffset, 72).ToArray()),
             new Region(headers.MetadataStartOffset, metadata[..prefixLength].ToArray())],
            headers.MetadataStartOffset + guidOffset);
    }

    public bool TryRead(SafeFileHandle file, out Guid mvid)
    {
        mvid = default;
        if (RandomAccess.GetLength(file) != fileLength) return false;
        Span<byte> buffer = stackalloc byte[MaxProbeBytes];
        foreach (var region in layout)
        {
            var bytes = buffer[..region.Bytes.Length];
            ReadExactly(file, bytes, region.Offset);
            if (!bytes.SequenceEqual(region.Bytes)) return false;
        }
        ReadExactly(file, buffer[..16], mvidOffset);
        mvid = new Guid(buffer[..16]);
        return true;
    }

    private static void ReadExactly(SafeFileHandle file, Span<byte> buffer, long offset)
    {
        while (!buffer.IsEmpty)
        {
            var count = RandomAccess.Read(file, buffer, offset);
            if (count == 0) throw new EndOfStreamException("Unity reference was truncated during validation.");
            buffer = buffer[count..];
            offset += count;
        }
    }

    private static bool ContainsStreamDirectory(ReadOnlySpan<byte> metadata, int tableOffset)
    {
        if (tableOffset < 20 || tableOffset > metadata.Length) return false;
        var versionLength = BinaryPrimitives.ReadInt32LittleEndian(metadata.Slice(12, 4));
        if (versionLength < 0 || versionLength > tableOffset - 20) return false;
        var position = 16 + versionLength;
        var streamCount = BinaryPrimitives.ReadUInt16LittleEndian(metadata.Slice(position + 2, 2));
        position += 4;
        for (var index = 0; index < streamCount; index++)
        {
            if (position > tableOffset - 8) return false;
            position += 8;
            var end = metadata[position..tableOffset].IndexOf((byte)0);
            if (end < 0) return false;
            position = (position + end + 4) & ~3;
        }
        return position <= tableOffset;
    }

    private sealed record Region(int Offset, byte[] Bytes);
}
