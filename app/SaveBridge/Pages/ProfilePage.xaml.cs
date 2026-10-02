using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media.Imaging;
using SaveBridge.Services;

namespace SaveBridge.Pages;

public sealed partial class ProfilePage : Page
{
    static readonly XboxLive Xbl = XboxLive.Instance;
    List<XboxTitle> _titles = [];

    public ProfilePage()
    {
        InitializeComponent();
        Loaded += async (_, _) => await RefreshAsync();
        Xbl.Changed += OnChanged;
        Unloaded += (_, _) => Xbl.Changed -= OnChanged;
    }

    void OnChanged(object? sender, EventArgs e) => DispatcherQueue.TryEnqueue(async () => await RefreshAsync());

    async Task RefreshAsync()
    {
        var p = Xbl.Profile;
        var signedIn = Xbl.SignedIn && p != null;
        SignIn.Visibility = signedIn ? Visibility.Collapsed : Visibility.Visible;
        SignOut.Visibility = signedIn ? Visibility.Visible : Visibility.Collapsed;
        SignedOutPanel.Visibility = signedIn ? Visibility.Collapsed : Visibility.Visible;
        SignedInPanel.Visibility = signedIn ? Visibility.Visible : Visibility.Collapsed;
        if (!signedIn)
        {
            Gamertag.Text = "Xbox profile";
            Gamerscore.Text = "Sign in to see your games and achievements.";
            Picture.ProfilePicture = null;
            return;
        }
        Gamertag.Text = p!.Gamertag;
        Gamerscore.Text = $"{p.Gamerscore:N0} Gamerscore";
        if (Uri.TryCreate(p.PictureUrl, UriKind.Absolute, out var pic)) Picture.ProfilePicture = new BitmapImage(pic);
        if (_titles.Count > 0) return;
        Busy.IsActive = true;
        try
        {
            _titles = (await Xbl.GetTitlesAsync())
                .Where(t => t.Achievement is { TotalAchievements: > 0 })
                .ToList();
            Filter();
        }
        catch (Exception ex) { ShowError(ex.Message); }
        finally { Busy.IsActive = false; }
    }

    async void SignIn_Click(object sender, RoutedEventArgs e)
    {
        Busy.IsActive = true;
        Error.IsOpen = false;
        try { await Xbl.SignInAsync(new SignInWindow()); }
        catch (Exception ex) { ShowError(ex.Message); }
        finally { Busy.IsActive = false; }
    }

    void SignOut_Click(object sender, RoutedEventArgs e)
    {
        _titles = [];
        Titles.ItemsSource = null;
        AchievementList.ItemsSource = null;
        Xbl.SignOut();
    }

    void Search_TextChanged(AutoSuggestBox sender, AutoSuggestBoxTextChangedEventArgs args) => Filter();

    void Filter()
    {
        var q = Search.Text.Trim();
        Titles.ItemsSource = _titles.Where(t => q.Length == 0 || t.Name.Contains(q, StringComparison.OrdinalIgnoreCase)).ToList();
    }

    async void Titles_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (Titles.SelectedItem is not XboxTitle t) return;
        TitleName.Text = t.Name;
        TitleSummary.Text = "Loading achievements…";
        AchievementList.ItemsSource = null;
        try
        {
            var list = await Xbl.GetAchievementsAsync(t.TitleId);
            if (Titles.SelectedItem != t) return;
            var events = list.Count(a => !a.TitleManaged);
            TitleSummary.Text = $"{t.Progress}. " + (events == 0
                ? "All title-managed: the game awards them itself."
                : events == list.Count
                    ? "All event-based: Xbox Live counts them from play, so an imported save won't unlock them."
                    : $"{events} event-based (counted by Xbox Live from play), {list.Count - events} title-managed.");
            AchievementList.ItemsSource = list.OrderBy(a => a.Unlocked).ThenBy(a => a.Name).ToList();
        }
        catch (Exception ex) { TitleSummary.Text = ex.Message; }
    }

    void ShowError(string message)
    {
        Error.Title = "Xbox sign-in";
        Error.Message = message;
        Error.IsOpen = true;
    }
}
