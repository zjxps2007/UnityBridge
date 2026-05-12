using System;
using System.IO;
using System.Text;

namespace UnityBridgeConnector
{
    public static class AtomicFile
    {
        static readonly Encoding s_Utf8 = new UTF8Encoding(false);

        public static void WriteAllText(string path, string contents)
        {
            var directory = Path.GetDirectoryName(path);
            if (!string.IsNullOrEmpty(directory))
                Directory.CreateDirectory(directory);

            var tempPath = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
            File.WriteAllText(tempPath, contents, s_Utf8);

            try
            {
                if (File.Exists(path))
                    File.Replace(tempPath, path, null);
                else
                    File.Move(tempPath, path);
            }
            finally
            {
                try
                {
                    if (File.Exists(tempPath))
                        File.Delete(tempPath);
                }
                catch
                {
                }
            }
        }
    }
}
