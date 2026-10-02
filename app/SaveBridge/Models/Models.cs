namespace SaveBridge.Models;

// Shapes of the converter's --json output (see savebridge/cli.py).

public sealed class GameInfo
{
    public string Id { get; set; } = "";
    public string Name { get; set; } = "";
    public long? SteamAppId { get; set; }
    public string XboxPackage { get; set; } = "";
    public List<string> Verified { get; set; } = [];
    public string Note { get; set; } = "";

    public bool SteamToXboxVerified => Verified.Contains("steam-to-xbox");
    public string Status => Verified.Count > 0
        ? (string.IsNullOrEmpty(Note) || !Note.Contains("partly") ? "Verified in game" : "Partly working")
        : "Tested on sample saves";
    public string StatusGlyph => Status == "Verified in game" ? "" : ""; // check / warning
}

public sealed class SteamAccountInfo
{
    public long Steamid64 { get; set; }
    public string Name { get; set; } = "";
    public bool SignedIn { get; set; }
    public bool HasSaves { get; set; }
    public override string ToString() =>
        (string.IsNullOrEmpty(Name) ? Steamid64.ToString() : $"{Name} ({Steamid64})") + (SignedIn ? " · signed in" : "");
}

public sealed class XboxAccountInfo
{
    public long Xuid { get; set; }
    public string Folder { get; set; } = "";
    public string? Gamertag { get; set; }
    public override string ToString() => Gamertag is null ? $"XUID {Xuid}" : $"{Gamertag} ({Xuid})";
}

public sealed class AccountsInfo
{
    public bool SteamPerPc { get; set; }
    public bool XboxPerPc { get; set; }
    public List<SteamAccountInfo> Steam { get; set; } = [];
    public List<XboxAccountInfo> Xbox { get; set; } = [];
}

public sealed class PlatformSaves
{
    public string? Account { get; set; }
    public string? Path { get; set; }
    public string? Error { get; set; }
    public List<string> Warnings { get; set; } = [];
    public Dictionary<string, string> Saves { get; set; } = [];
}

public sealed class SaveListing
{
    public PlatformSaves Steam { get; set; } = new();
    public PlatformSaves Xbox { get; set; } = new();
}

public sealed record SaveRow(string Key, string Steam, string Xbox);

public sealed class ReadinessCheck
{
    public string Code { get; set; } = "";
    public string Status { get; set; } = "";
    public string Message { get; set; } = "";
    public string Action { get; set; } = "";
}

public sealed class ReadinessReport
{
    public bool Ready { get; set; }
    public List<ReadinessCheck> Checks { get; set; } = [];
    public bool TargetReady => Checks.Any(c => c.Code == "target-account" && c.Status == "pass")
        && Checks.Where(c => c.Code != "source-saves").All(c => c.Status == "pass");
    public string Steps => string.Join("\n", Checks.Where(c => c.Status != "pass").Select(c => c.Action).Distinct());
}

public sealed class BackupInfo
{
    public string Game { get; set; } = "";
    public string Name { get; set; } = "";
    public string Path { get; set; } = "";
    public DateTime Time { get; set; }
    public string Platform { get; set; } = "";
    public string Account { get; set; } = "";
    public long Size { get; set; }

    public string When => Time.ToString("g");
    public string Where => Platform == "xbox" ? "Xbox" : "Steam";
    public string SizeText => Size < 1 << 20 ? $"{Size / 1024.0:F0} KB" : $"{Size / 1048576.0:F1} MB";
}
