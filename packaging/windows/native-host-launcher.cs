using System;
using System.Diagnostics;
using System.IO;

internal static class LocalTubeDubNativeHostLauncher
{
    private const uint MaxMessageBytes = 64 * 1024 * 1024;

    private static string Quote(string value)
    {
        return "\"" + value.Replace("\"", "\\\"") + "\"";
    }

    private static byte[] ReadExactly(Stream input, int length)
    {
        byte[] data = new byte[length];
        int offset = 0;
        while (offset < length)
        {
            int count = input.Read(data, offset, length - offset);
            if (count <= 0)
            {
                throw new EndOfStreamException("Native Messaging frame ended early.");
            }
            offset += count;
        }
        return data;
    }

    private static byte[] ReadNativeFrame(Stream input)
    {
        byte[] header = ReadExactly(input, 4);
        uint length = BitConverter.ToUInt32(header, 0);
        if (length > MaxMessageBytes)
        {
            throw new InvalidDataException("Native Messaging frame is too large.");
        }
        byte[] payload = ReadExactly(input, checked((int)length));
        byte[] frame = new byte[header.Length + payload.Length];
        Buffer.BlockCopy(header, 0, frame, 0, header.Length);
        Buffer.BlockCopy(payload, 0, frame, header.Length, payload.Length);
        return frame;
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

        byte[] requestFrame;
        try
        {
            requestFrame = ReadNativeFrame(Console.OpenStandardInput());
        }
        catch (Exception error)
        {
            Console.Error.WriteLine("LocalTube Dub Native Host received an invalid request: " + error.Message);
            return 4;
        }

        ProcessStartInfo startInfo = new ProcessStartInfo();
        startInfo.FileName = python;
        startInfo.Arguments = Quote(host);
        startInfo.WorkingDirectory = runtimeRoot;
        startInfo.UseShellExecute = false;
        startInfo.CreateNoWindow = true;
        startInfo.RedirectStandardInput = true;
        startInfo.RedirectStandardOutput = true;
        startInfo.RedirectStandardError = false;
        startInfo.EnvironmentVariables["LOCAL_DUB_NATIVE_INPUT_UTF8_BOM_COMPAT"] = "1";

        using (Process child = Process.Start(startInfo))
        {
            if (child == null)
            {
                Console.Error.WriteLine("LocalTube Dub Native Host failed to start.");
                return 3;
            }
            try
            {
                Stream childInput = child.StandardInput.BaseStream;
                childInput.Write(requestFrame, 0, requestFrame.Length);
                childInput.Flush();
                child.StandardInput.Close();

                byte[] responseFrame = ReadNativeFrame(child.StandardOutput.BaseStream);
                Stream output = Console.OpenStandardOutput();
                output.Write(responseFrame, 0, responseFrame.Length);
                output.Flush();

                if (!child.WaitForExit(5000))
                {
                    child.Kill();
                    child.WaitForExit();
                }
                return child.ExitCode;
            }
            catch (Exception error)
            {
                if (!child.HasExited)
                {
                    child.Kill();
                    child.WaitForExit();
                }
                Console.Error.WriteLine("LocalTube Dub Native Host bridge failed: " + error.Message);
                return 5;
            }
        }
    }
}
