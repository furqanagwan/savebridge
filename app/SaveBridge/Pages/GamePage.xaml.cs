using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Navigation;
using SaveBridge.Models;
using SaveBridge.Services;
using Windows.Storage.Pickers;

namespace SaveBridge.Pages;

public sealed partial class GamePage : Page
{
    GameInfo _game = new();
    AccountsInfo _accounts = new();
    bool _loadingAccounts;
    bool _writing;
    int _readinessVersion;
    ReadinessReport? _xboxReadiness, _steamReadiness;

    public GamePage() => InitializeComponent();

    protected override async void OnNavigatedTo(NavigationEventArgs e)
    {
        _game = (GameInfo)e.Parameter;
        GameTitle.Text = _game.Name;
        StatusText.Text = _game.Status;
        StatusIcon.Glyph = _game.StatusGlyph;
        var brush = (Brush)Application.Current.Resources[
            _game.Status == "Verified in game" ? "SystemFillColorSuccessBrush" : "SystemFillColorCautionBrush"];
        StatusIcon.Foreground = StatusText.Foreground = brush;
        Note.Text = _game.Note;
        Note.Visibility = string.IsNullOrEmpty(_game.Note) ? Visibility.Collapsed : Visibility.Visible;
        await LoadAccountsAsync();
        await LoadSavesAsync();
        await LoadAchievementsAsync();
    }

    // ---- loading ----------------------------------------------------------------

    async Task LoadAccountsAsync()
    {
        _loadingAccounts = true;
        try
        {
            _accounts = await Cli.JsonAsync<AccountsInfo>("accounts", _game.Id);
            var me = XboxLive.Instance.Profile;
            foreach (var x in _accounts.Xbox)
                if (me != null && x.Xuid.ToString() == me.Xuid) x.Gamertag = me.Gamertag;
            SteamAccount.ItemsSource = _accounts.Steam;
            SteamAccount.SelectedItem = _accounts.Steam.FirstOrDefault(a => a.SignedIn) ?? _accounts.Steam.FirstOrDefault();
            SteamAccount.IsEnabled = _accounts.Steam.Count > 1;
            SteamAccount.PlaceholderText = _accounts.SteamPerPc ? "Saves are per PC" : "No Steam account found";
            XboxAccount.ItemsSource = _accounts.Xbox;
            XboxAccount.SelectedItem = _accounts.Xbox.FirstOrDefault();
            XboxAccount.IsEnabled = _accounts.Xbox.Count > 1;
            XboxAccount.PlaceholderText = _accounts.XboxPerPc ? "Saves are per PC"
                : "Start the Xbox version once on your profile";
        }
        catch (Exception e)
        {
            Show(InfoBarSeverity.Error, "Couldn't read accounts", e.Message);
        }
        finally { _loadingAccounts = false; }
    }

    IEnumerable<string> AccountArgs()
    {
        if (SteamAccount.SelectedItem is SteamAccountInfo s) { yield return "--steam-account"; yield return s.Steamid64.ToString(); }
        if (XboxAccount.SelectedItem is XboxAccountInfo x) { yield return "--xbox-account"; yield return x.Xuid.ToString(); }
    }

    async Task LoadSavesAsync()
    {
        Busy.IsActive = true;
        try
        {
            var list = await Cli.JsonAsync<SaveListing>(["list", _game.Id, .. AccountArgs()]);
            var keys = list.Steam.Saves.Keys.Concat(list.Xbox.Saves.Keys).Distinct().ToList();
            var order = keys.ToDictionary(k => k, k => (list.Steam.Saves.Keys.ToList().IndexOf(k) is var i and >= 0 ? i : 1000)
                                                        + (list.Xbox.Saves.Keys.ToList().IndexOf(k) is var j and >= 0 ? j : 1000));
            Saves.ItemsSource = keys.OrderBy(k => order[k]).Select(k => new SaveRow(k,
                list.Steam.Saves.GetValueOrDefault(k) ?? "—", list.Xbox.Saves.GetValueOrDefault(k) ?? "—")).ToList();
            var problems = new[] { ("Steam", list.Steam), ("Xbox", list.Xbox) }
                .SelectMany(p => (p.Item2.Error is { } err ? [err] : p.Item2.Warnings).Select(w => $"{p.Item1}: {w}"))
                .ToList();
            Log.Text = string.Join("\n", new[] { $"Steam: {list.Steam.Path ?? list.Steam.Error}",
                                                 $"Xbox:  {list.Xbox.Path ?? list.Xbox.Error}" }.Concat(problems));
            SavesHint.Text = keys.Count == 0
                ? "No saves found on either store yet."
                : "Tick saves to copy only those; with none ticked, the game's usual set is copied.";
        }
        catch (Exception e)
        {
            Show(InfoBarSeverity.Error, "Couldn't read saves", e.Message);
        }
        finally { Busy.IsActive = false; }
        await LoadReadinessAsync();
    }

    async Task LoadReadinessAsync()
    {
        var version = ++_readinessVersion;
        _xboxReadiness = _steamReadiness = null;
        ReadinessXbox.IsOpen = ReadinessSteam.IsOpen = false;
        UpdateActions();
        var accountArgs = AccountArgs().ToArray();
        try
        {
            var xbox = Cli.JsonAsync<ReadinessReport>(["check", _game.Id, "--to", "xbox", "--from", "steam", .. accountArgs]);
            var steam = Cli.JsonAsync<ReadinessReport>(["check", _game.Id, "--to", "steam", "--from", "xbox", .. accountArgs]);
            await Task.WhenAll(xbox, steam);
            if (version != _readinessVersion) return;
            _xboxReadiness = await xbox;
            _steamReadiness = await steam;
            ShowReadiness(ReadinessXbox, "Steam → Xbox", _xboxReadiness);
            ShowReadiness(ReadinessSteam, "Xbox → Steam", _steamReadiness);
        }
        catch (Exception)
        {
            if (version != _readinessVersion) return;
            ReadinessXbox.Title = "Could not check conversion prerequisites";
            ReadinessXbox.Message = "Refresh to check again. You can inspect a downloaded save for more details.";
            ReadinessXbox.Severity = InfoBarSeverity.Warning;
            ReadinessXbox.IsOpen = true;
        }
        finally { if (version == _readinessVersion) UpdateActions(); }
    }

    static void ShowReadiness(InfoBar bar, string direction, ReadinessReport report)
    {
        bar.Title = direction + (report.Ready ? " is ready" : " needs attention");
        bar.Message = report.Ready ? "Your selected accounts and conversion prerequisites are ready." : report.Steps;
        bar.Severity = report.Ready ? InfoBarSeverity.Success : InfoBarSeverity.Warning;
        bar.IsOpen = true;
    }

    async Task LoadAchievementsAsync()
    {
        Achievements.IsOpen = false;
        var xbl = XboxLive.Instance;
        if (!xbl.SignedIn || string.IsNullOrEmpty(_game.XboxPackage)) return;
        try
        {
            var title = (await xbl.GetTitlesAsync()).FirstOrDefault(t =>
                t.Pfn?.StartsWith(_game.XboxPackage + "_", StringComparison.OrdinalIgnoreCase) == true);
            if (title is null) return;
            var list = await xbl.GetAchievementsAsync(title.TitleId);
            var events = list.Count(a => !a.TitleManaged);
            Achievements.Title = $"Your Xbox achievements: {title.Progress}";
            Achievements.Message = list.Count == 0 ? "" : events == 0
                ? "All of this game's achievements are title-managed: the game awards them itself, so some may unlock after loading an imported save."
                : $"{events} of {list.Count} achievements are event-based: Xbox Live counts them from what you do in game, so an imported save can't unlock them.";
            Achievements.IsOpen = true;
        }
        catch
        {
            // Achievements are a bonus; the page works without them.
        }
    }

    // ---- actions ----------------------------------------------------------------

    List<string> Selection() => Saves.SelectedItems.OfType<SaveRow>().Select(r => r.Key).ToList();

    List<string> WriteOptions()
    {
        var args = new List<string>();
        var keys = Selection();
        if (keys.Count > 0) { args.Add("--only"); args.Add(string.Join(",", keys)); }
        else if (IncludeAll.IsChecked == true) args.Add("--all");
        if (!string.IsNullOrWhiteSpace(SlotMap.Text)) { args.Add("--slot-map"); args.Add(SlotMap.Text.Trim()); }
        args.AddRange(AccountArgs());
        return args;
    }

    async void ToXbox_Click(object sender, RoutedEventArgs e) =>
        await PreviewAndWriteAsync(["convert", _game.Id, "steam-to-xbox", .. WriteOptions()], "Copy Steam saves to Xbox?");

    async void ToSteam_Click(object sender, RoutedEventArgs e) =>
        await PreviewAndWriteAsync(["convert", _game.Id, "xbox-to-steam", .. WriteOptions()], "Copy Xbox saves to Steam?");

    async void Import_Click(object sender, RoutedEventArgs e)
    {
        var parts = ((string)((MenuFlyoutItem)sender).Tag).Split('|');
        var path = parts[1] == "folder" ? await PickFolderAsync() : await PickFileAsync();
        if (path is null) return;
        var into = parts[0] == "xbox" ? "Xbox" : "Steam";
        await PreviewAndWriteAsync(["import", _game.Id, path, "--to", parts[0], .. WriteOptions()],
                                   $"Import this save into {into}?");
    }

    async void Refresh_Click(object sender, RoutedEventArgs e) => await LoadSavesAsync();

    async void Inspect_Click(object sender, RoutedEventArgs e)
    {
        var folder = (string)((MenuFlyoutItem)sender).Tag == "folder";
        var path = folder ? await PickFolderAsync() : await PickFileAsync();
        if (path is null) return;
        SetBusy(true);
        try
        {
            var report = await Cli.RunAsync("inspect", path, "--game", _game.Id);
            if (!report.Ok) { Show(InfoBarSeverity.Error, "Could not inspect save", LastLine(report)); return; }
            var dialog = new ContentDialog
            {
                XamlRoot = XamlRoot, Title = "Save inspection", PrimaryButtonText = "Copy report",
                CloseButtonText = "Close", DefaultButton = ContentDialogButton.Close,
                Content = new ScrollViewer
                {
                    MaxHeight = 480,
                    Content = new TextBlock { Text = report.Output, TextWrapping = TextWrapping.Wrap,
                                              IsTextSelectionEnabled = true, FontSize = 13 },
                },
            };
            if (await dialog.ShowAsync() == ContentDialogResult.Primary)
            {
                var package = new Windows.ApplicationModel.DataTransfer.DataPackage();
                package.SetText(report.Output);
                Windows.ApplicationModel.DataTransfer.Clipboard.SetContent(package);
            }
        }
        catch (Exception error) { Show(InfoBarSeverity.Error, "Could not inspect save", error.Message); }
        finally { SetBusy(false); }
    }

    async void Account_Changed(object sender, SelectionChangedEventArgs e)
    {
        if (!_loadingAccounts) await LoadSavesAsync();
    }

    async Task PreviewAndWriteAsync(List<string> args, string question)
    {
        Result.IsOpen = false;
        SetBusy(true);
        try
        {
            var to = args[0] == "convert" ? (args[2] == "steam-to-xbox" ? "xbox" : "steam")
                                         : args[args.IndexOf("--to") + 1];
            var checkArgs = new List<string> { "check", _game.Id, "--to", to };
            if (args[0] == "convert") checkArgs.AddRange(["--from", to == "xbox" ? "steam" : "xbox"]);
            checkArgs.AddRange(AccountArgs());
            var readiness = await Cli.JsonAsync<ReadinessReport>(checkArgs.ToArray());
            if (!readiness.Ready)
            {
                Show(InfoBarSeverity.Warning, "Conversion needs attention", readiness.Steps);
                return;
            }
            var preview = await Cli.RunAsync([.. args, "--dry-run"]);
            Log.Text = preview.Text;
            if (!preview.Ok)
            {
                Show(InfoBarSeverity.Error, "Nothing was written", LastLine(preview));
                return;
            }
            var dialog = new ContentDialog
            {
                XamlRoot = XamlRoot,
                Title = question,
                PrimaryButtonText = "Write",
                CloseButtonText = "Cancel",
                DefaultButton = ContentDialogButton.Close,
                Content = new ScrollViewer
                {
                    MaxHeight = 420,
                    Content = new TextBlock
                    {
                        Text = preview.Output.Replace("Dry run: nothing written.", "").Trim() +
                               "\n\nThe current saves are backed up first. Make sure the game is closed.",
                        FontFamily = new FontFamily("Consolas"), FontSize = 12,
                        IsTextSelectionEnabled = true, TextWrapping = TextWrapping.Wrap,
                    },
                },
            };
            if (await dialog.ShowAsync() != ContentDialogResult.Primary) return;
            var run = await Cli.RunAsync(args);
            Log.Text = run.Text;
            if (run.Ok)
                Show(InfoBarSeverity.Success, "Done", string.Join(" ", run.Output.Split('\n')
                    .Where(l => l.StartsWith("Wrote") || l.StartsWith("Open the game") || l.StartsWith("If Steam")
                                || l.StartsWith("This game's"))));
            else
                Show(InfoBarSeverity.Error, "Something went wrong", LastLine(run));
            await LoadSavesAsync();
        }
        catch (Exception e) { Show(InfoBarSeverity.Error, "Could not convert save", e.Message); }
        finally { SetBusy(false); }
    }

    static string LastLine(CliResult r) =>
        (r.Error.Length > 0 ? r.Error : r.Output).Split('\n').LastOrDefault(l => l.Trim().Length > 0)?
        .Replace("error: ", "") ?? "Unknown error";

    void SetBusy(bool busy)
    {
        _writing = busy;
        Busy.IsActive = busy;
        SteamAccount.IsEnabled = !busy && _accounts.Steam.Count > 1;
        XboxAccount.IsEnabled = !busy && _accounts.Xbox.Count > 1;
        UpdateActions();
    }

    void UpdateActions()
    {
        ToXbox.IsEnabled = !_writing && _xboxReadiness?.Ready == true;
        ToSteam.IsEnabled = !_writing && _steamReadiness?.Ready == true;
        ImportSave.IsEnabled = InspectSave.IsEnabled = !_writing;
        ImportXboxFolder.IsEnabled = ImportXboxFile.IsEnabled = !_writing && _xboxReadiness?.TargetReady == true;
        ImportSteamFolder.IsEnabled = ImportSteamFile.IsEnabled = !_writing && _steamReadiness?.TargetReady == true;
    }

    void Show(InfoBarSeverity severity, string title, string message)
    {
        Result.Severity = severity;
        Result.Title = title;
        Result.Message = message;
        Result.IsOpen = true;
    }

    // ---- pickers (unpackaged apps must attach them to the window) ----------------

    static nint Hwnd => WinRT.Interop.WindowNative.GetWindowHandle(App.Window!);

    static async Task<string?> PickFolderAsync()
    {
        var picker = new FolderPicker { SuggestedStartLocation = PickerLocationId.Downloads };
        picker.FileTypeFilter.Add("*");
        WinRT.Interop.InitializeWithWindow.Initialize(picker, Hwnd);
        return (await picker.PickSingleFolderAsync())?.Path;
    }

    static async Task<string?> PickFileAsync()
    {
        var picker = new FileOpenPicker { SuggestedStartLocation = PickerLocationId.Downloads };
        picker.FileTypeFilter.Add("*");
        WinRT.Interop.InitializeWithWindow.Initialize(picker, Hwnd);
        return (await picker.PickSingleFileAsync())?.Path;
    }
}
