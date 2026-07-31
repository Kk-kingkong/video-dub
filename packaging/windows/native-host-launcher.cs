using System;
using System.Diagnostics;
using System.IO;

internal static class LocalTubeDubNativeHostLauncher
{
    private static string Quote(string value)
    {
        return "\"" + value.Replace("\"", "\\\"") + "\"";
    }

    public static int Main()
    {
        string companionDirectory = AppDomain.CurrentDomain.BaseDirectory;
        string runtimeRoot = Path.GetFullPath(Path.Combine(companionDirectory, ".."));
        string python = Path.Combine(runtimeRoot, ".venv", "python.exe");
        string host = Path.Combine(companionDirectory, "native_host.py");
        if (!File.Exists(python) || !File.Exists(host))
        {
            Console.Error.WriteLine("LocalTube Dub Native Host runtime is incomplete.");
            return 2;
        }

        ProcessStartInfo startInfo = new ProcessStartInfo();
        startInfo.FileName = python;
        startInfo.Arguments = Quote(host);
        startInfo.WorkingDirectory = runtimeRoot;
        startInfo.UseShellExecute = false;
        startInfo.CreateNoWindow = true;
        startInfo.RedirectStandardInput = false;
        startInfo.RedirectStandardOutput = false;
        startInfo.RedirectStandardError = false;

        using (Process child = Process.Start(startInfo))
        {
            if (child == null)
            {
                Console.Error.WriteLine("LocalTube Dub Native Host failed to start.");
                return 3;
            }
            child.WaitForExit();
            return child.ExitCode;
        }
    }
}
