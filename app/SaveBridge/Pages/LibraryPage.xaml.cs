using System.Collections.ObjectModel;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media.Imaging;
using SaveBridge.Models;
using SaveBridge.Services;

namespace SaveBridge.Pages;

public sealed partial class LibraryPage : Page, IAppPage
{
    static readonly Library Lib = Library.Instance;
    readonly ObservableCollection<LibraryGame> _shown = [];
    List<LibraryGame> _featured = [];
    int _featuredIndex;
    string _filter = "";
    string? _lastOpened;
    bool _focusPending;
    DispatcherQueueTimer? _rotate;

    public LibraryPage()
    {
        InitializeComponent();
        NavigationCacheMode = Microsoft.UI.Xaml.Navigation.NavigationCacheMode.Required;
        Games.ItemsSource = _shown;
        // Focus asked for before the covers existed: give it to the cover as soon as it is created.
        Games.ContainerContentChanging += (_, args) =>
        {
            if (_focusPending && !args.InRecycleQueue && args.ItemIndex == FocusIndex())
                DispatcherQueue.TryEnqueue(DispatcherQueuePriority.Low, FocusDefault);
        };
        Loaded += (_, _) =>
        {
            Lib.Changed += OnLibraryChanged;
            Show();
            _rotate ??= DispatcherQueue.CreateTimer();
            _rotate.Interval = TimeSpan.FromSeconds(9);
            _rotate.Tick += Rotate;
            _rotate.Start();
        };
        Unloaded += (_, _) =>
        {
            Lib.Changed -= OnLibraryChanged;
            if (_rotate != null) { _rotate.Stop(); _rotate.Tick -= Rotate; }
        };
    }

    void OnLibraryChanged(object? sender, EventArgs e) => DispatcherQueue.TryEnqueue(Show);

    void Show()
    {
        LoadingBar.Visibility = Lib.Loaded ? Visibility.Collapsed : Visibility.Visible;
        Error.Title = "Something went wrong";
        Error.Message = Lib.Error ?? "";
        Error.IsOpen = Lib.Error != null;
        Apply();
        var featured = Lib.Games.Where(g => g.HeroUri != null).OrderByDescending(g => g.HasSaves).ThenBy(g => g.Name).ToList();
        if (featured.Count != _featured.Count)
        {
            _featured = featured;
            HeroPips.NumberOfPages = Math.Min(featured.Count, 99);
            ShowFeatured(Math.Min(_featuredIndex, Math.Max(0, featured.Count - 1)));
        }
        else if (_featured.Count == 0) ShowFeatured(0);
    }

    // ---- featured banner ---------------------------------------------------------------

    void ShowFeatured(int index)
    {
        if (_featured.Count == 0)
        {
            HeroTitle.Text = "Your game saves, on Steam and Xbox";
            HeroText.Text = "Pick a game to see its saves on both stores, copy them across, or import a save you downloaded.";
            HeroOpen.Visibility = HeroNext.Visibility = Visibility.Collapsed;
            HeroImage.Source = null;
            HeroLogo.Source = null;
            return;
        }
        _featuredIndex = index % _featured.Count;
        var g = _featured[_featuredIndex];
        HeroImage.Source = new BitmapImage(g.HeroUri);
        HeroLogo.Source = g.LogoUri is { } logo ? new BitmapImage(logo) : null;
        HeroLogo.Visibility = Ui.Show(g.HasLogo);
        HeroTitle.Text = g.Name;
        HeroTitle.Visibility = Ui.Hide(g.HasLogo);
        HeroText.Text = g.Description;
        HeroOpen.Visibility = HeroNext.Visibility = Visibility.Visible;
        HeroOpen.Tag = g.Id;
        AutomationProperties.SetName(HeroOpen, $"Open {g.Name}");
        if (HeroPips.SelectedPageIndex != _featuredIndex) HeroPips.SelectedPageIndex = _featuredIndex;
    }

    void Rotate(DispatcherQueueTimer sender, object args)
    {
        // Don't move the banner while someone is using it.
        if (HeroOpen.FocusState != FocusState.Unfocused || HeroNext.FocusState != FocusState.Unfocused) return;
        if (_featured.Count > 1) ShowFeatured(_featuredIndex + 1);
    }

    void HeroNext_Click(object sender, RoutedEventArgs e) => ShowFeatured(_featuredIndex + 1);

    void HeroPips_SelectedIndexChanged(PipsPager sender, PipsPagerSelectedIndexChangedEventArgs args)
    {
        if (sender.SelectedPageIndex != _featuredIndex) ShowFeatured(sender.SelectedPageIndex);
    }

    void HeroOpen_Click(object sender, RoutedEventArgs e)
    {
        if (HeroOpen.Tag is string id) App.Window!.Navigate(typeof(GamePage), id);
    }

    // ---- grid --------------------------------------------------------------------------

    public void SetFilter(string text)
    {
        _filter = text;
        Apply();
    }

    void Apply()
    {
        var tag = (Filters.SelectedItem?.Tag as string) ?? "all";
        IEnumerable<LibraryGame> items = Lib.Games.Where(g => tag switch
        {
            "installed" => g.SteamInstalled || g.XboxInstalled,
            "saves" => g.HasSaves,
            "verified" => g.Verified,
            _ => true,
        });
        if (_filter.Length > 0)
            items = items.Where(g => g.Name.Contains(_filter, StringComparison.OrdinalIgnoreCase)
                                     || g.Id.Contains(_filter, StringComparison.OrdinalIgnoreCase));
        items = Sort.SelectedIndex switch
        {
            1 => items.OrderByDescending(g => g.LastSaved ?? DateTime.MinValue).ThenBy(g => g.Name),
            2 => items.OrderByDescending(g => g.Meta?.Released ?? DateTime.MinValue).ThenBy(g => g.Name),
            _ => items.OrderBy(g => g.Name, StringComparer.OrdinalIgnoreCase),
        };
        var list = items.ToList();
        if (!list.SequenceEqual(_shown))
        {
            _shown.Clear();
            foreach (var g in list) _shown.Add(g);
        }
        Count.Text = list.Count == Lib.Games.Count ? $"{list.Count} games" : $"{list.Count} of {Lib.Games.Count} games";
    }

    void Filters_SelectionChanged(SelectorBar sender, SelectorBarSelectionChangedEventArgs args) => Apply();

    void Sort_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (Games != null) Apply();
    }

    void Games_ItemClick(object sender, ItemClickEventArgs e)
    {
        _lastOpened = ((LibraryGame)e.ClickedItem).Id;
        App.Window!.Navigate(typeof(GamePage), _lastOpened);
    }

    // ---- IAppPage ------------------------------------------------------------------------

    public Task RefreshAsync() => Lib.LoadAsync(refresh: true);

    public void FocusDefault()
    {
        // Coming back from a game: focus that game again, so the D-pad picks up where it left off.
        _focusPending = Games.ContainerFromIndex(FocusIndex()) is not GridViewItem item || !item.Focus(MainWindow.FocusMode);
    }

    int FocusIndex() => _lastOpened is null ? 0 : Math.Max(0, _shown.ToList().FindIndex(g => g.Id == _lastOpened));
}
