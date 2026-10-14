using System.Text.Json;
using System.Text.Json.Nodes;
using SaveBridge.Models;

namespace SaveBridge.Services;

/// <summary>
/// Game art and details from Steam's public store service (no key, no sign-in):
/// IStoreBrowseService/GetItems returns every asset's current (hashed) path, so
/// one request covers the whole library. Cached for a week; offline uses the cache.
/// </summary>
public static class Metadata
{
    const string Cdn = "https://shared.akamai.steamstatic.com/store_item_assets/";
    static readonly HttpClient Http = new() { Timeout = TimeSpan.FromSeconds(15) };
    static readonly JsonSerializerOptions Json = new() { WriteIndented = false };
    static readonly TimeSpan MaxAge = TimeSpan.FromDays(7);
    static string CacheFile => Path.Combine(AppSettings.Folder, "metadata.json");

    public static async Task<Dictionary<long, GameMeta>> GetAsync(IEnumerable<long> appIds, bool refresh = false)
    {
        var cache = Load();
        var wanted = appIds.Distinct().ToList();
        var stale = wanted.Where(id => refresh || !cache.TryGetValue(id, out var m) || DateTime.UtcNow - m.Fetched > MaxAge).ToList();
        if (stale.Count > 0)
        {
            try
            {
                foreach (var batch in stale.Chunk(50))
                    foreach (var meta in await FetchAsync(batch))
                        cache[meta.AppId] = meta;
                Save(cache);
            }
            catch (Exception)
            {
                // Offline or rate-limited: whatever is cached still shows.
            }
        }
        return wanted.Where(cache.ContainsKey).ToDictionary(id => id, id => cache[id]);
    }

    public static void ClearCache()
    {
        try { File.Delete(CacheFile); } catch (IOException) { }
    }

    static async Task<List<GameMeta>> FetchAsync(IEnumerable<long> ids)
    {
        var request = new JsonObject
        {
            ["ids"] = new JsonArray(ids.Select(id => (JsonNode)new JsonObject { ["appid"] = id }).ToArray()),
            ["context"] = new JsonObject { ["language"] = "english", ["country_code"] = "US" },
            ["data_request"] = new JsonObject
            {
                ["include_assets"] = true, ["include_basic_info"] = true,
                ["include_release"] = true, ["include_reviews"] = true,
            },
        };
        var url = "https://api.steampowered.com/IStoreBrowseService/GetItems/v1?input_json=" +
                  Uri.EscapeDataString(request.ToJsonString());
        var root = JsonNode.Parse(await Http.GetStringAsync(url));
        var list = new List<GameMeta>();
        foreach (var item in root?["response"]?["store_items"]?.AsArray() ?? [])
        {
            if (item?["success"]?.GetValue<int>() != 1) continue;
            var assets = item["assets"];
            var format = assets?["asset_url_format"]?.GetValue<string>();
            string? Asset(params string[] keys)
            {
                foreach (var k in keys)
                    if (format != null && assets?[k]?.GetValue<string>() is { Length: > 0 } file)
                        return Cdn + format.Replace("${FILENAME}", file);
                return null;
            }
            var basic = item["basic_info"];
            long? released = item["release"]?["steam_release_date"]?.GetValue<long>();
            list.Add(new GameMeta
            {
                AppId = item["appid"]!.GetValue<long>(),
                Name = item["name"]?.GetValue<string>() ?? "",
                Description = basic?["short_description"]?.GetValue<string>()?.Trim() ?? "",
                Developers = Names(basic?["developers"]),
                Publishers = Names(basic?["publishers"]),
                Released = released is > 0 ? DateTimeOffset.FromUnixTimeSeconds(released.Value).LocalDateTime : null,
                Reviews = item["reviews"]?["summary_filtered"]?["review_score_label"]?.GetValue<string>(),
                Cover = Asset("library_capsule_2x", "library_capsule"),
                Hero = Asset("library_hero_2x", "library_hero"),
                Logo = Asset("library_logo_2x", "library_logo"),
                Header = Asset("header_2x", "header", "main_capsule"),
                Fetched = DateTime.UtcNow,
            });
        }
        return list;
    }

    static List<string> Names(JsonNode? node) =>
        node?.AsArray().Select(n => n?["name"]?.GetValue<string>()).OfType<string>().ToList() ?? [];

    static Dictionary<long, GameMeta> Load()
    {
        try
        {
            var list = JsonSerializer.Deserialize<List<GameMeta>>(File.ReadAllText(CacheFile), Json) ?? [];
            return list.ToDictionary(m => m.AppId);
        }
        catch (Exception)
        {
            return [];
        }
    }

    static void Save(Dictionary<long, GameMeta> cache)
    {
        Directory.CreateDirectory(AppSettings.Folder);
        File.WriteAllText(CacheFile, JsonSerializer.Serialize(cache.Values.ToList(), Json));
    }
}
