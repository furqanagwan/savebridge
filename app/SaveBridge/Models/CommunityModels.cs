namespace SaveBridge.Models;

// `savebridge community list --json` (see savebridge/community.py).

public sealed class CommunityTest
{
    public string Platform { get; set; } = "";
    public string By { get; set; } = "";
    public string GameVersion { get; set; } = "";
}

public sealed class CommunitySaveEntry
{
    public string Key { get; set; } = "";
    public string Summary { get; set; } = "";
}

public sealed class CommunitySave
{
    public string Id { get; set; } = "";
    public string Game { get; set; } = "";
    public string GameName { get; set; } = "";
    public string Title { get; set; } = "";
    public string Description { get; set; } = "";
    public string Author { get; set; } = "";
    public string Platform { get; set; } = "";
    public string PlatformName { get; set; } = "";
    public string GameVersion { get; set; } = "";
    public List<CommunityTest> Tested { get; set; } = [];
    public List<CommunitySaveEntry> Saves { get; set; } = [];
    public long Size { get; set; }
    public string? Created { get; set; }

    /// <summary>The description, under a name that doesn't clash with page elements in x:Bind.</summary>
    public string Notes => Description;
    public string Byline => $"by {Author} · from {PlatformName} · game version {GameVersion}";
    public string TestedText => Tested.Count == 0
        ? "Not tested yet"
        : "Tested on " + string.Join(", ", Tested.Select(t => Names.GetValueOrDefault(t.Platform, t.Platform)).Distinct());
    public bool IsTested => Tested.Count > 0;
    public string SizeText => Size < 1 << 20 ? $"{Size / 1024.0:F0} KB" : $"{Size / 1048576.0:F1} MB";
    public string PlatformShort => Platform switch
    {
        "steam" => "STEAM", "xbox-pc" => "XBOX PC", "xbox-series" => "XBOX SERIES",
        "ps3" => "PS3", "ps4" => "PS4", "ps5" => "PS5", _ => Platform.ToUpperInvariant(),
    };

    static readonly Dictionary<string, string> Names = new()
    {
        ["steam"] = "Steam", ["xbox-pc"] = "Xbox PC", ["xbox-series"] = "Xbox Series X|S",
        ["ps3"] = "PS3", ["ps4"] = "PS4", ["ps5"] = "PS5",
    };
}

public sealed class DownloadResult
{
    public string Path { get; set; } = "";
}
