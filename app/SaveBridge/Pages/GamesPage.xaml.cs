using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Runtime.CompilerServices;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using SaveBridge.Models;
using SaveBridge.Services;

namespace SaveBridge.Pages;

public sealed class GameCard(GameInfo info) : INotifyPropertyChanged
{
    public GameInfo Info { get; } = info;
    public Brush StatusBrush => (Brush)Application.Current.Resources[
        Info.Status == "Verified in game" ? "SystemFillColorSuccessBrush" : "SystemFillColorCautionBrush"];

    string _steam = "Steam: …", _xbox = "Xbox: …";
    public string SteamState { get => _steam; set => Set(ref _steam, value); }
    public string XboxState { get => _xbox; set => Set(ref _xbox, value); }

    public event PropertyChangedEventHandler? PropertyChanged;
    void Set(ref string field, string value, [CallerMemberName] string? name = null)
    {
        field = value;
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
    }
}

public sealed partial class GamesPage : Page
{
    static List<GameCard>? _cache;
    readonly ObservableCollection<GameCard> _shown = [];

    public GamesPage()
    {
        InitializeComponent();
        NavigationCacheMode = Microsoft.UI.Xaml.Navigation.NavigationCacheMode.Required;
        Grid.ItemsSource = _shown;
        Loaded += async (_, _) => await LoadAsync();
    }

    async Task LoadAsync()
    {
        if (_cache != null) { Filter(); Busy.IsActive = false; return; }
        try
        {
            var games = await Cli.JsonAsync<List<GameInfo>>("games");
            _cache = games.OrderBy(g => g.Name, StringComparer.OrdinalIgnoreCase).Select(g => new GameCard(g)).ToList();
            Filter();
            // Which stores have this game: one small query per game, a few at a time.
            using var gate = new SemaphoreSlim(4);
            await Task.WhenAll(_cache.Select(async card =>
            {
                await gate.WaitAsync();
                try
                {
                    var a = await Cli.JsonAsync<AccountsInfo>("accounts", card.Info.Id);
                    card.SteamState = a.SteamPerPc ? "Steam: per PC" : a.Steam.Any(s => s.HasSaves) ? "Steam: saves found" : "Steam: no saves";
                    card.XboxState = a.XboxPerPc ? "Xbox: per PC" : a.Xbox.Count > 0 ? "Xbox: ready" : "Xbox: not played";
                }
                catch
                {
                    card.SteamState = card.XboxState = "";
                }
                finally { gate.Release(); }
            }));
        }
        catch (Exception e)
        {
            Error.Title = "Couldn't run the converter";
            Error.Message = e.Message;
            Error.IsOpen = true;
        }
        finally { Busy.IsActive = false; }
    }

    void Filter()
    {
        var q = Search.Text.Trim();
        _shown.Clear();
        foreach (var c in _cache ?? [])
            if (q.Length == 0 || c.Info.Name.Contains(q, StringComparison.OrdinalIgnoreCase)
                              || c.Info.Id.Contains(q, StringComparison.OrdinalIgnoreCase))
                _shown.Add(c);
    }

    void Search_TextChanged(AutoSuggestBox sender, AutoSuggestBoxTextChangedEventArgs args) => Filter();

    void Grid_ItemClick(object sender, ItemClickEventArgs e) =>
        Frame.Navigate(typeof(GamePage), ((GameCard)e.ClickedItem).Info);
}
