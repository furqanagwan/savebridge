using System.Diagnostics;
using System.Text;
using System.Text.Json;

namespace SaveBridge.Services;

public sealed record CliResult(int ExitCode, string Output, string Error)
{
    public bool Ok => ExitCode == 0;
    public string Text => string.IsNullOrWhiteSpace(Error) ? Output : $"{Output}\n{Error}".Trim();
}

/// <summary>
/// Runs the savebridge converter. The app has no conversion logic of its own:
/// everything goes through the same command line the README documents.
/// </summary>
public static class Cli
{
    static readonly JsonSerializerOptions Json = new()
    {
        PropertyNameCaseInsensitive = true,
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
    };

    /// <summary>How the converter is started, found once: a bundled exe, SAVEBRIDGE_CLI, or the repo.</summary>
    static readonly Lazy<(string File, string Prefix, string? WorkDir)> Launcher = new(FindLauncher);

    public static string Describe => Launcher.Value.File + " " + Launcher.Value.Prefix;

    static (string, string, string?) FindLauncher()
    {
        var env = Environment.GetEnvironmentVariable("SAVEBRIDGE_CLI");
        if (!string.IsNullOrEmpty(env) && File.Exists(env))
            return (env, "", null);
        var bundled = Path.Combine(AppContext.BaseDirectory, "cli", "savebridge.exe");
        if (File.Exists(bundled))
            return (bundled, "", null);
        // Development: run the package from the repository this app was built in.
        for (var dir = new DirectoryInfo(AppContext.BaseDirectory); dir != null; dir = dir.Parent)
            if (File.Exists(Path.Combine(dir.FullName, "savebridge", "__main__.py")))
                return ("python", "-m savebridge", dir.FullName);
        return ("python", "-m savebridge", null);
    }

    public static async Task<CliResult> RunAsync(IEnumerable<string> args, CancellationToken ct = default)
    {
        var (file, prefix, workDir) = Launcher.Value;
        var psi = new ProcessStartInfo(file)
        {
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
        };
        if (workDir != null) psi.WorkingDirectory = workDir;
        foreach (var a in prefix.Split(' ', StringSplitOptions.RemoveEmptyEntries)) psi.ArgumentList.Add(a);
        foreach (var a in args) psi.ArgumentList.Add(a);
        psi.Environment["PYTHONUTF8"] = "1";
        psi.Environment["PYTHONIOENCODING"] = "utf-8";
        try
        {
            using var p = Process.Start(psi)!;
            var stdout = p.StandardOutput.ReadToEndAsync(ct);
            var stderr = p.StandardError.ReadToEndAsync(ct);
            await p.WaitForExitAsync(ct);
            return new CliResult(p.ExitCode, (await stdout).TrimEnd(), (await stderr).TrimEnd());
        }
        catch (System.ComponentModel.Win32Exception e)
        {
            return new CliResult(-1, "", $"Could not start the converter ({file}): {e.Message}. " +
                                        "Install Python 3.10+ or use a release build.");
        }
    }

    public static Task<CliResult> RunAsync(params string[] args) => RunAsync((IEnumerable<string>)args);

    public static async Task<T> JsonAsync<T>(params string[] args)
    {
        var r = await RunAsync(args.Append("--json"));
        if (!r.Ok) throw new InvalidOperationException(r.Text);
        return JsonSerializer.Deserialize<T>(r.Output, Json)
               ?? throw new InvalidOperationException("The converter returned no data.");
    }
}
