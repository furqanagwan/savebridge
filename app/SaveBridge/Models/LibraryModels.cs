using System.ComponentModel;

namespace SaveBridge.Models;

// ---- `savebridge locate --json` ------------------------------------------------------

public sealed class LocateExtra
{
    public string Kind { get; set; } = "";
    public string Path { get; set; } = "";
}

public sealed class LocateSave
{
    public string Path { get; set; } = "";
    public bool Exists { get; set; }
    public int? Files { get; set; }
    public int? Containers { get; set; }
    public DateTime? Modified { get; set; }
    public string Account { get; set; } = "";
    public string Name { get; set; } = "";
    public List<LocateExtra> Extra { get; set; } = [];

    public string Who => Account switch
    {
        "this PC" => "Shared by every account on this PC",
        _ when !string.IsNullOrEmpty(Name) => $"{Name} ({Account})",
        _ => Account.Length > 12 ? $"Account {Account}" : Account,
    };

    public string Summary
    {
        get
        {
            if (!Exists) return "No saves yet";
            var what = Containers is { } c ? $"{c} save{(c == 1 ? "" : "s")} (Xbox cloud containers)"
                                           : $"{Files ?? 0} file{(Files == 1 ? "" : "s")}";
            return Modified is { } m ? $"{what} · last saved {m:g}" : what;
        }
    }
}

public sealed class LocateStore
{
    public long? AppId { get; set; }
    public string? PackagePrefix { get; set; }
    public string? Package { get; set; }
    public bool Installed { get; set; }
    public string? InstallDir { get; set; }
    public bool PerPc { get; set; }
    public bool CloudSaves { get; set; }
    public List<LocateSave> Saves { get; set; } = [];
    public string? Error { get; set; }

    public bool HasSaves => Saves.Any(s => s.Exists && (s.Files is > 0 || s.Containers is > 0));
}

public sealed class LocateInfo
{
    public string Id { get; set; } = "";
    public string Name { get; set; } = "";
    public LocateStore Steam { get; set; } = new();
    public LocateStore Xbox { get; set; } = new();
}

// ---- Steam store metadata --------------------------------------------------------------

public sealed class GameMeta
{
    public long AppId { get; set; }
    public string Name { get; set; } = "";
    public string Description { get; set; } = "";
    public List<string> Developers { get; set; } = [];
    public List<string> Publishers { get; set; } = [];
    public DateTime? Released { get; set; }
    public string? Reviews { get; set; }
    public string? Cover { get; set; }       // portrait 600x900
    public string? Hero { get; set; }        // wide library background
    public string? Logo { get; set; }
    public string? Header { get; set; }      // 460x215 landscape
    public DateTime Fetched { get; set; }
}

// ---- one game in the library -----------------------------------------------------------

public sealed class LibraryGame(GameInfo info) : INotifyPropertyChanged
{
    public GameInfo Info { get; } = info;
    LocateInfo? _location;
    GameMeta? _meta;

    public LocateInfo? Location { get => _location; set { _location = value; Changed(); } }
    public GameMeta? Meta { get => _meta; set { _meta = value; Changed(); } }

    public string Id => Info.Id;
    public string Name => Info.Name;
    public Uri? CoverUri => ToUri(Meta?.Cover ?? Meta?.Header);
    public Uri? HeroUri => ToUri(Meta?.Hero ?? Meta?.Header);
    public Uri? LogoUri => ToUri(Meta?.Logo);
    public bool HasCover => CoverUri != null;
    public bool HasLogo => LogoUri != null;
    public string Description => Meta?.Description is { Length: > 0 } d ? d : "";
    public string Credits => string.Join(" · ", new[]
    {
        Meta?.Developers.FirstOrDefault(),
        Meta?.Publishers.FirstOrDefault() is { } p && p != Meta?.Developers.FirstOrDefault() ? p : null,
        Meta?.Released?.ToString("yyyy"),
        Meta?.Reviews,
    }.Where(s => !string.IsNullOrEmpty(s)));

    public bool SteamInstalled => Location?.Steam.Installed == true;
    public bool XboxInstalled => Location?.Xbox.Installed == true;
    public bool HasSaves => Location is { } l && (l.Steam.HasSaves || l.Xbox.HasSaves);
    public bool Verified => Info.Verified.Count > 0;
    public string Status => Info.Status;

    public string SteamState => Location is null ? "Steam" :
        SteamInstalled ? (Location.Steam.HasSaves ? "Steam · saves" : "Steam · installed") :
        Location.Steam.HasSaves ? "Steam · saves only" : "Steam · not installed";
    public string XboxState => Location is null ? "Xbox" : string.IsNullOrEmpty(Info.XboxPackage) ? "Xbox · n/a" :
        XboxInstalled ? (Location.Xbox.HasSaves ? "Xbox · saves" : "Xbox · installed") :
        Location.Xbox.HasSaves ? "Xbox · saves only" : "Xbox · not installed";

    public DateTime? LastSaved => Location is null ? null :
        Location.Steam.Saves.Concat(Location.Xbox.Saves).Max(s => s.Modified);

    static Uri? ToUri(string? s) => Uri.TryCreate(s, UriKind.Absolute, out var u) ? u : null;

    public event PropertyChangedEventHandler? PropertyChanged;
    void Changed() => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(string.Empty)); // all computed properties
}
