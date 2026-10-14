using System.Collections.ObjectModel;
using SaveBridge.Models;

namespace SaveBridge.Services;

/// <summary>
/// Every supported game with where it is installed, where its saves are (both
/// stores) and its store art. Shared by all pages; loaded once, refreshed on demand.
/// </summary>
public sealed class Library
{
    public static Library Instance { get; } = new();

    public ObservableCollection<LibraryGame> Games { get; } = [];
    public bool Loaded { get; private set; }
    public string? Error { get; private set; }
    public event EventHandler? Changed;

    Task? _loading;

    public Task LoadAsync(bool refresh = false)
    {
        if (_loading is { IsCompleted: false }) return _loading;
        if (Loaded && !refresh) return Task.CompletedTask;
        return _loading = LoadCoreAsync(refresh);
    }

    async Task LoadCoreAsync(bool refresh)
    {
        Error = null;
        try
        {
            var gamesTask = Cli.JsonAsync<List<GameInfo>>("games");
            var locateTask = Cli.JsonAsync<List<LocateInfo>>("locate");
            var games = await gamesTask;
            var byId = Games.ToDictionary(g => g.Id);
            foreach (var g in games.OrderBy(g => g.Name, StringComparer.OrdinalIgnoreCase))
                if (!byId.ContainsKey(g.Id))
                {
                    var item = new LibraryGame(g);
                    byId[g.Id] = item;
                    Insert(item);
                }
            Changed?.Invoke(this, EventArgs.Empty);

            // Art and save locations arrive independently; whichever is ready shows first.
            var metaTask = Metadata.GetAsync(games.Where(g => g.SteamAppId is > 0).Select(g => g.SteamAppId!.Value), refresh);
            try
            {
                foreach (var loc in await locateTask)
                    if (byId.TryGetValue(loc.Id, out var item)) item.Location = loc;
            }
            catch (Exception e) { Error = "Couldn't find save locations: " + e.Message; }
            var meta = await metaTask;
            foreach (var item in Games)
                if (item.Info.SteamAppId is { } id && meta.TryGetValue(id, out var m)) item.Meta = m;
            Loaded = true;
        }
        catch (Exception e)
        {
            Error = e.Message;
        }
        Changed?.Invoke(this, EventArgs.Empty);
    }

    /// <summary>Re-reads one game's save locations (after a write or restore).</summary>
    public async Task RefreshLocationAsync(string id)
    {
        if (Find(id) is not { } item) return;
        try { item.Location = (await Cli.JsonAsync<List<LocateInfo>>("locate", id)).FirstOrDefault(); }
        catch (Exception) { }
    }

    public LibraryGame? Find(string id) => Games.FirstOrDefault(g => g.Id == id);

    void Insert(LibraryGame item)
    {
        var i = 0;
        while (i < Games.Count && string.Compare(Games[i].Name, item.Name, StringComparison.OrdinalIgnoreCase) < 0) i++;
        Games.Insert(i, item);
    }
}
