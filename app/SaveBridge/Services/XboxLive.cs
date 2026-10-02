using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using XboxAuthNet.OAuth;
using XboxAuthNet.OAuth.CodeFlow;
using XboxAuthNet.XboxLive;
using XboxAuthNet.XboxLive.Crypto;
using XboxAuthNet.XboxLive.Requests;

namespace SaveBridge.Services;

public sealed record XboxProfile(string Xuid, string Gamertag, long Gamerscore, string? PictureUrl);

public sealed class XboxTitle
{
    public string TitleId { get; set; } = "";
    public string Name { get; set; } = "";
    public string? Pfn { get; set; }
    public string? DisplayImage { get; set; }
    public List<string> Devices { get; set; } = [];
    public TitleAchievementSummary? Achievement { get; set; }

    public string Progress => Achievement is null || Achievement.TotalAchievements == 0
        ? "No achievements"
        : $"{Achievement.CurrentAchievements}/{Achievement.TotalAchievements} achievements · " +
          $"{Achievement.CurrentGamerscore}/{Achievement.TotalGamerscore} G";
    public double Percent => Achievement?.ProgressPercentage ?? 0;
    public Uri? ImageUri => Uri.TryCreate(DisplayImage, UriKind.Absolute, out var u) ? u : null;
}

public sealed class TitleAchievementSummary
{
    public int CurrentAchievements { get; set; }
    public int TotalAchievements { get; set; }
    public int CurrentGamerscore { get; set; }
    public int TotalGamerscore { get; set; }
    public double ProgressPercentage { get; set; }
}

public sealed class Achievement
{
    public string Id { get; set; } = "";
    public string Name { get; set; } = "";
    public string? Description { get; set; }
    public string? LockedDescription { get; set; }
    public string ProgressState { get; set; } = "";
    public bool IsSecret { get; set; }
    public Progression? Progression { get; set; }
    public List<Reward> Rewards { get; set; } = [];
    public List<MediaAsset> MediaAssets { get; set; } = [];

    const string ZeroGuid = "00000000-0000-0000-0000-000000000000";

    /// <summary>Awarded by the game itself (true) or by Xbox Live from event-driven stats (false).</summary>
    public bool TitleManaged => Progression?.Requirements is not { Count: > 0 } r || r[0].Id == ZeroGuid;
    public string Kind => TitleManaged ? "Title-managed" : "Event-based";
    public bool Unlocked => ProgressState == "Achieved";
    public string State => Unlocked ? "Unlocked" : ProgressState == "InProgress" ? "In progress" : "Locked";
    public int Gamerscore => Rewards.Where(r => r.Type == "Gamerscore").Select(r => int.TryParse(r.Value, out var v) ? v : 0).Sum();
    public string Text => Unlocked || !IsSecret ? (Unlocked ? Description : LockedDescription ?? Description) ?? "" : "Secret achievement";
    public string? Icon => MediaAssets.FirstOrDefault(m => m.Type == "Icon")?.Url;
    public Uri? IconUri => Uri.TryCreate(Icon, UriKind.Absolute, out var u) ? u : null;
    public double Opacity => Unlocked ? 1 : 0.6;
    public string GamerscoreText => $"{Gamerscore} G";
}

public sealed class Progression { public List<Requirement> Requirements { get; set; } = []; }
public sealed class Requirement { public string Id { get; set; } = ""; public string? Current { get; set; } public string? Target { get; set; } }
public sealed class Reward { public string Type { get; set; } = ""; public string? Value { get; set; } }
public sealed class MediaAsset { public string? Name { get; set; } public string? Type { get; set; } public string? Url { get; set; } }

/// <summary>
/// Read-only access to the signed-in user's own Xbox data: the normal Microsoft
/// sign-in (OAuth, the Xbox app's public client ID), then Xbox Live SISU
/// authorization, the same route as Xbox Achievement Unlocker's "OAuth login".
/// Nothing is read from other programs, and nothing is ever written to Xbox Live.
/// </summary>
public sealed class XboxLive
{
    public const string XboxAppClientId = "000000004424da1f";
    static readonly HttpClient Http = new();
    static readonly JsonSerializerOptions Json = new() { PropertyNameCaseInsensitive = true };
    static string TokenFile => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "savebridge", "xbox-signin.bin");

    public static XboxLive Instance { get; } = new();

    string? _auth;   // "XBL3.0 x=<uhs>;<token>"
    public XboxProfile? Profile { get; private set; }
    public bool SignedIn => _auth != null;
    public event EventHandler? Changed;

    CodeFlowLiveApiClient ApiClient => new(XboxAppClientId, XboxAuthConstants.XboxScope, Http);

    /// <summary>Sign in again from the saved refresh token, if there is one.</summary>
    public async Task<bool> TrySilentAsync()
    {
        var refresh = LoadRefreshToken();
        if (refresh is null) return false;
        try
        {
            var flow = new CodeFlowBuilder(ApiClient).Build();
            await FinishAsync(await flow.AuthenticateSilently(refresh, CancellationToken.None));
            return true;
        }
        catch
        {
            DeleteToken();
            return false;
        }
    }

    public async Task SignInAsync(IWebUI webUi)
    {
        var flow = new CodeFlowBuilder(ApiClient).WithWebUI(webUi).Build();
        await FinishAsync(await flow.AuthenticateInteractively(CancellationToken.None));
    }

    public void SignOut()
    {
        _auth = null;
        Profile = null;
        DeleteToken();
        Changed?.Invoke(this, EventArgs.Empty);
    }

    async Task FinishAsync(MicrosoftOAuthResponse oauth)
    {
        var signer = new XboxRequestSigner(new ECDCertificatePopCryptoProvider());
        var device = await new XboxDeviceTokenRequest { DeviceType = "Win32", DeviceVersion = "0.0.0" }
            .Send(Http, signer);
        var sisu = await new XboxSisuAuthRequest
        {
            AccessToken = oauth.AccessToken,
            ClientId = XboxAppClientId,
            DeviceToken = device.Token,
            RelyingParty = XboxAuthConstants.XboxLiveRelyingParty,
        }.Send(Http, signer);
        var token = sisu.AuthorizationToken ?? throw new InvalidOperationException("Xbox Live refused the sign-in.");
        var claims = token.XuiClaims ?? throw new InvalidOperationException("Xbox Live returned no user.");
        _auth = $"XBL3.0 x={claims.UserHash};{token.Token}";
        if (!string.IsNullOrEmpty(oauth.RefreshToken)) SaveRefreshToken(oauth.RefreshToken);
        Profile = await LoadProfileAsync(claims.XboxUserId ?? "");
        Changed?.Invoke(this, EventArgs.Empty);
    }

    // ---- API ------------------------------------------------------------------

    async Task<JsonDocument> GetAsync(string url, string contract = "2")
    {
        if (_auth is null) throw new InvalidOperationException("Not signed in to Xbox.");
        using var req = new HttpRequestMessage(HttpMethod.Get, url);
        req.Headers.TryAddWithoutValidation("Authorization", _auth);
        req.Headers.Add("x-xbl-contract-version", contract);
        req.Headers.AcceptLanguage.Add(new StringWithQualityHeaderValue(
            System.Globalization.CultureInfo.CurrentUICulture.Name is { Length: > 0 } n ? n : "en-US"));
        using var res = await Http.SendAsync(req);
        var body = await res.Content.ReadAsStringAsync();
        if (!res.IsSuccessStatusCode)
            throw new InvalidOperationException($"Xbox Live: {(int)res.StatusCode} {res.ReasonPhrase}");
        return JsonDocument.Parse(body);
    }

    async Task<XboxProfile> LoadProfileAsync(string xuid)
    {
        using var doc = await GetAsync("https://profile.xboxlive.com/users/me/profile/settings" +
                                       "?settings=Gamertag,Gamerscore,GameDisplayPicRaw");
        var user = doc.RootElement.GetProperty("profileUsers")[0];
        var settings = user.GetProperty("settings").EnumerateArray()
            .ToDictionary(s => s.GetProperty("id").GetString()!, s => s.GetProperty("value").GetString());
        return new XboxProfile(user.GetProperty("id").GetString() ?? xuid,
            settings.GetValueOrDefault("Gamertag") ?? "",
            long.TryParse(settings.GetValueOrDefault("Gamerscore"), out var gs) ? gs : 0,
            settings.GetValueOrDefault("GameDisplayPicRaw"));
    }

    public async Task<List<XboxTitle>> GetTitlesAsync()
    {
        using var doc = await GetAsync($"https://titlehub.xboxlive.com/users/xuid({Profile!.Xuid})/titles/" +
                                       "titleHistory/decoration/Achievement,detail,scid?maxItems=10000");
        return doc.RootElement.GetProperty("titles").Deserialize<List<XboxTitle>>(Json) ?? [];
    }

    public async Task<List<Achievement>> GetAchievementsAsync(string titleId)
    {
        using var doc = await GetAsync($"https://achievements.xboxlive.com/users/xuid({Profile!.Xuid})/" +
                                       $"achievements?titleId={titleId}&maxItems=1000");
        return doc.RootElement.GetProperty("achievements").Deserialize<List<Achievement>>(Json) ?? [];
    }

    // ---- remembered sign-in (encrypted for this Windows user with DPAPI) ---------

    static void SaveRefreshToken(string token)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(TokenFile)!);
        File.WriteAllBytes(TokenFile, ProtectedData.Protect(Encoding.UTF8.GetBytes(token), null,
                                                            DataProtectionScope.CurrentUser));
    }

    static string? LoadRefreshToken()
    {
        try
        {
            return Encoding.UTF8.GetString(ProtectedData.Unprotect(File.ReadAllBytes(TokenFile), null,
                                                                   DataProtectionScope.CurrentUser));
        }
        catch
        {
            return null;
        }
    }

    static void DeleteToken()
    {
        try { File.Delete(TokenFile); } catch (IOException) { }
    }
}
