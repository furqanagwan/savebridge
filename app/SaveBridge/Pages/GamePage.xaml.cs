using Microsoft.UI;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;
using Microsoft.UI.Xaml.Navigation;
using SaveBridge.Models;
using SaveBridge.Services;
using Windows.Storage.Pickers;

namespace SaveBridge.Pages;

public sealed partial class GamePage : Page, IAppPage
{
    LibraryGame _game = new(new GameInfo());
    AccountsInfo _accounts = new();
    bool _loadingAccounts, _writing, _achievementsLoaded;
    int _readinessVersion;
    ReadinessReport? _xboxReadiness, _steamReadiness;

    public GamePage() => InitializeComponent();

    protected override async void OnNavigatedTo(NavigationEventArgs e)
    {
        var id = e.Parameter as string ?? "";
        await Library.Instance.LoadAsync();
        _game = Library.Instance.Find(id) ?? new LibraryGame(new GameInfo { Id = id, Name = id });
        _game.PropertyChanged += (_, _) => DispatcherQueue.TryEnqueue(ShowHeader);
        ShowHeader();
        Crumbs.ItemsSource = new[] { "Library", _game.Name };
        Note.Title = "Known limits";
        Note.Message = _game.Info.Note;
        Note.IsOpen = !string.IsNullOrEmpty(_game.Info.Note);
        await LoadAccountsAsync();
        await LoadSavesAsync();
    }

    // ---- header and locations ---------------------------------------------------------

    void ShowHeader()
    {
        HeroImage.Source = _game.HeroUri is { } hero ? new BitmapImage(hero) : null;
        Logo.Source = _game.LogoUri is { } logo ? new BitmapImage(logo) : null;
        Logo.Visibility = Ui.Show(_game.HasLogo);
        GameTitle.Text = _game.Name;
        GameTitle.Visibility = Ui.Hide(_game.HasLogo);
        Credits.Text = _game.Credits;
        Description.Text = _game.Description;
        Description.Visibility = Ui.ShowText(_game.Description);
        var verified = _game.Status == "Verified in game";
        StatusChip.Background = new SolidColorBrush(verified ? ColorHelper.FromArgb(0xE6, 0x10, 0x7C, 0x10)
                                                             : ColorHelper.FromArgb(0xE6, 0x9D, 0x5D, 0x00));
        StatusIcon.Glyph = verified ? "" : "";
        StatusText.Text = _game.Status;
        ShowLocations();
    }

    void ShowLocations()
    {
        var loc = _game.Location;
        if (loc is null)
        {
            SteamInstall.Text = XboxInstall.Text = "Looking…";
            return;
        }
        var s = loc.Steam;
        SteamInstall.Text = s.Installed ? "Installed" : "Not installed";
        SteamDir.Text = s.InstallDir ?? "Not installed on this PC";
        SteamDirOpen.Tag = s.InstallDir;
        SteamDirOpen.IsEnabled = s.Installed;
        SteamSaves.ItemsSource = s.Saves;
        SteamNote.Text = s.Error ?? (s.PerPc
            ? "This game keeps one set of Steam saves for the whole PC."
            : "Steam keeps a save folder per Steam account. Steam Cloud syncs it when the game closes.");

        var x = loc.Xbox;
        XboxInstall.Text = string.IsNullOrEmpty(_game.Info.XboxPackage) ? "No Xbox PC version supported"
                         : x.Installed ? "Installed" : "Not installed";
        XboxDir.Text = x.InstallDir ?? (x.Installed ? "Installed (folder protected by Windows)" : "Not installed on this PC");
        XboxDirOpen.Tag = x.InstallDir;
        XboxDirOpen.IsEnabled = x.InstallDir != null;
        XboxSaves.ItemsSource = x.Saves;
        XboxNote.Text = x.Error ?? (x.PerPc
            ? "The Xbox version writes plain files on this PC; they don't sync to the Xbox cloud."
            : x.Saves.Count == 0
                ? "No Xbox save folder yet. Start the Xbox version once while signed in, and save."
                : "Xbox cloud saves: one folder per Xbox profile, uploaded by the Xbox app while the game runs.");
    }

    void OpenFolder_Click(object sender, RoutedEventArgs e) => Ui.OpenFolder(((FrameworkElement)sender).Tag as string);

    void CopyPath_Click(object sender, RoutedEventArgs e)
    {
        if (((FrameworkElement)sender).Tag is string path)
        {
            Ui.CopyText(path);
            Show(InfoBarSeverity.Success, "Copied", path);
        }
    }

    void Crumbs_ItemClicked(BreadcrumbBar sender, BreadcrumbBarItemClickedEventArgs args)
    {
        if (args.Index == 0) App.Window!.Navigate(typeof(LibraryPage));
    }

    async void Tabs_SelectionChanged(SelectorBar sender, SelectorBarSelectionChangedEventArgs args)
    {
        var tag = sender.SelectedItem?.Tag as string;
        SavesPanel.Visibility = Ui.Show(tag == "saves");
        LocationsPanel.Visibility = Ui.Show(tag == "locations");
        AchievementsPanel.Visibility = Ui.Show(tag == "achievements");
        BackupsPanel.Visibility = Ui.Show(tag == "backups");
        if (tag == "achievements" && !_achievementsLoaded) await LoadAchievementsAsync();
        if (tag == "backups") await LoadBackupsAsync();
    }

    // ---- accounts and saves -------------------------------------------------------------

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
            XboxAccount.PlaceholderText = _accounts.XboxPerPc ? "Saves are per PC" : "Start the Xbox version once on your profile";
        }
        catch (Exception e) { Show(InfoBarSeverity.Error, "Couldn't read accounts", e.Message); }
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
            var steamKeys = list.Steam.Saves.Keys.ToList();
            var xboxKeys = list.Xbox.Saves.Keys.ToList();
            var keys = steamKeys.Concat(xboxKeys).Distinct()
                .OrderBy(k => (steamKeys.IndexOf(k) is var i and >= 0 ? i : 1000) + (xboxKeys.IndexOf(k) is var j and >= 0 ? j : 1000))
                .ToList();
            Saves.ItemsSource = keys.Select(k => new SaveRow(k,
                list.Steam.Saves.GetValueOrDefault(k) ?? "—", list.Xbox.Saves.GetValueOrDefault(k) ?? "—")).ToList();
            var problems = new[] { ("Steam", list.Steam), ("Xbox", list.Xbox) }
                .SelectMany(p => (p.Item2.Error is { } err ? [err] : p.Item2.Warnings).Select(w => $"{p.Item1}: {w}"));
            Log.Text = string.Join("\n", new[] { $"Steam: {list.Steam.Path ?? list.Steam.Error}",
                                                 $"Xbox:  {list.Xbox.Path ?? list.Xbox.Error}" }.Concat(problems));
            SavesHint.Text = keys.Count == 0
                ? "No saves found on either store yet. Import a downloaded save, or play and save once."
                : "Select saves to copy only those; with none selected, the game's usual set is copied.";
        }
        catch (Exception e) { Show(InfoBarSeverity.Error, "Couldn't read saves", e.Message); }
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
            ReadinessXbox.Title = "Couldn't check what a conversion needs";
            ReadinessXbox.Message = "Refresh to check again, or inspect a downloaded save for details.";
            ReadinessXbox.Severity = InfoBarSeverity.Warning;
            ReadinessXbox.IsOpen = true;
        }
        finally { if (version == _readinessVersion) UpdateActions(); }
    }

    static void ShowReadiness(InfoBar bar, string direction, ReadinessReport report)
    {
        bar.Title = direction + (report.Ready ? " is ready" : " needs attention");
        bar.Message = report.Ready ? "Your selected accounts and everything the conversion needs are ready." : report.Steps;
        bar.Severity = report.Ready ? InfoBarSeverity.Success : InfoBarSeverity.Warning;
        bar.IsOpen = true;
    }

    async void Account_Changed(object sender, SelectionChangedEventArgs e)
    {
        if (!_loadingAccounts) await LoadSavesAsync();
    }

    // ---- achievements and backups -------------------------------------------------------

    async Task LoadAchievementsAsync()
    {
        var xbl = XboxLive.Instance;
        AchievementsSignedOut.Visibility = Ui.Hide(xbl.SignedIn);
        AchievementsSignedIn.Visibility = Ui.Show(xbl.SignedIn);
        if (!xbl.SignedIn) return;
        if (string.IsNullOrEmpty(_game.Info.XboxPackage))
        {
            AchievementTitle.Text = "This game has no Xbox PC version in savebridge.";
            return;
        }
        AchievementTitle.Text = "Loading your achievements…";
        AchievementRing.IsIndeterminate = true;
        try
        {
            var title = (await xbl.GetTitlesAsync()).FirstOrDefault(t =>
                t.Pfn?.StartsWith(_game.Info.XboxPackage + "_", StringComparison.OrdinalIgnoreCase) == true);
            if (title is null)
            {
                AchievementTitle.Text = "You haven't played the Xbox version yet.";
                AchievementKinds.Text = "";
                return;
            }
            var list = await xbl.GetAchievementsAsync(title.TitleId);
            var events = list.Count(a => !a.TitleManaged);
            AchievementRing.Value = title.Percent;
            AchievementTitle.Text = title.Progress;
            AchievementKinds.Text = list.Count == 0 ? "" : events == 0
                ? "All title-managed: the game awards them itself, so some may unlock soon after loading an imported save."
                : $"{events} of {list.Count} are event-based: Xbox Live counts them from play, so an imported save can't unlock them.";
            AchievementList.ItemsSource = list.OrderBy(a => a.Unlocked).ThenBy(a => a.Name).ToList();
            _achievementsLoaded = true;
        }
        catch (Exception e) { AchievementTitle.Text = "Couldn't load achievements: " + e.Message; }
        finally { AchievementRing.IsIndeterminate = false; }
    }

    void SignIn_Click(object sender, RoutedEventArgs e) => App.Window!.Navigate(typeof(ProfilePage));

    async Task LoadBackupsAsync()
    {
        try
        {
            var list = await Cli.JsonAsync<List<BackupInfo>>("backups", _game.Id);
            BackupList.ItemsSource = list;
            NoBackups.Visibility = Ui.Show(list.Count == 0);
        }
        catch (Exception e) { Show(InfoBarSeverity.Error, "Couldn't list backups", e.Message); }
    }

    async void Restore_Click(object sender, RoutedEventArgs e)
    {
        var b = (BackupInfo)((Button)sender).Tag;
        await RunWriteAsync(["restore", _game.Id, b.Name], $"Restore the {b.Where} saves from {b.When}?", "Restore");
        await LoadBackupsAsync();
    }

    // ---- writing --------------------------------------------------------------------------

    List<string> Selection() => Saves.SelectedItems.OfType<SaveRow>().Select(r => r.Key).ToList();

    List<string> WriteOptions()
    {
        var args = new List<string>();
        var keys = Selection();
        if (keys.Count > 0) { args.Add("--only"); args.Add(string.Join(",", keys)); }
        else if (IncludeAll.IsOn) args.Add("--all");
        if (!string.IsNullOrWhiteSpace(SlotMap.Text)) { args.Add("--slot-map"); args.Add(SlotMap.Text.Trim()); }
        args.AddRange(AccountArgs());
        return args;
    }

    async void ToXbox_Click(object sender, RoutedEventArgs e) =>
        await CheckedWriteAsync(["convert", _game.Id, "steam-to-xbox", .. WriteOptions()], "xbox", "steam", "Copy Steam saves to Xbox?");

    async void ToSteam_Click(object sender, RoutedEventArgs e) =>
        await CheckedWriteAsync(["convert", _game.Id, "xbox-to-steam", .. WriteOptions()], "steam", "xbox", "Copy Xbox saves to Steam?");

    async void Import_Click(object sender, RoutedEventArgs e)
    {
        var parts = ((string)((MenuFlyoutItem)sender).Tag).Split('|');
        var path = parts[1] == "folder" ? await PickFolderAsync() : await PickFileAsync();
        if (path is null) return;
        await CheckedWriteAsync(["import", _game.Id, path, "--to", parts[0], .. WriteOptions()], parts[0], null,
                                $"Import this save into {(parts[0] == "xbox" ? "Xbox" : "Steam")}?");
    }

    async void Refresh_Click(object sender, RoutedEventArgs e) => await RefreshAsync();

    async void Inspect_Click(object sender, RoutedEventArgs e)
    {
        var path = (string)((MenuFlyoutItem)sender).Tag == "folder" ? await PickFolderAsync() : await PickFileAsync();
        if (path is null) return;
        SetBusy(true);
        try
        {
            var report = await Cli.RunAsync("inspect", path, "--game", _game.Id);
            if (!report.Ok) { Show(InfoBarSeverity.Error, "Couldn't inspect the save", Writes.LastLine(report)); return; }
            var dialog = new ContentDialog
            {
                XamlRoot = XamlRoot, Title = "Save inspection", PrimaryButtonText = "Copy report",
                CloseButtonText = "Close", DefaultButton = ContentDialogButton.Close,
                Content = new ScrollViewer
                {
                    MaxHeight = 480,
                    Content = new TextBlock { Text = report.Output, TextWrapping = TextWrapping.Wrap, IsTextSelectionEnabled = true },
                },
            };
            if (await dialog.ShowAsync() == ContentDialogResult.Primary) Ui.CopyText(report.Output);
        }
        catch (Exception error) { Show(InfoBarSeverity.Error, "Couldn't inspect the save", error.Message); }
        finally { SetBusy(false); }
    }

    /// <summary>Check prerequisites, then preview and write.</summary>
    async Task CheckedWriteAsync(List<string> args, string to, string? from, string question)
    {
        Result.IsOpen = false;
        SetBusy(true);
        ReadinessReport readiness;
        try
        {
            var check = new List<string> { "check", _game.Id, "--to", to };
            if (from != null) check.AddRange(["--from", from]);
            check.AddRange(AccountArgs());
            readiness = await Cli.JsonAsync<ReadinessReport>(check.ToArray());
        }
        catch (Exception e)
        {
            Show(InfoBarSeverity.Error, "Couldn't check the conversion", e.Message);
            SetBusy(false);
            return;
        }
        if (!readiness.Ready)
        {
            Show(InfoBarSeverity.Warning, "This needs attention first", readiness.Steps);
            SetBusy(false);
            return;
        }
        await RunWriteAsync(args, question);
    }

    async Task RunWriteAsync(List<string> args, string question, string confirm = "Write")
    {
        Result.IsOpen = false;
        SetBusy(true);
        try
        {
            var r = await Writes.PreviewAndRunAsync(XamlRoot, args, question, confirm);
            Log.Text = r.Log;
            switch (r.Outcome)
            {
                case WriteOutcome.Done: Show(InfoBarSeverity.Success, "Done", r.Summary); break;
                case WriteOutcome.Refused: Show(InfoBarSeverity.Error, "Nothing was written", r.Summary); break;
                case WriteOutcome.Failed: Show(InfoBarSeverity.Error, "Something went wrong", r.Summary); break;
            }
            if (r.Outcome == WriteOutcome.Done)
            {
                await LoadSavesAsync();
                await Library.Instance.RefreshLocationAsync(_game.Id);
            }
        }
        catch (Exception e) { Show(InfoBarSeverity.Error, "Couldn't write the saves", e.Message); }
        finally { SetBusy(false); }
    }

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

    // ---- IAppPage ---------------------------------------------------------------------------

    public async Task RefreshAsync()
    {
        await Library.Instance.RefreshLocationAsync(_game.Id);
        await LoadSavesAsync();
        if (AchievementsPanel.Visibility == Visibility.Visible) await LoadAchievementsAsync();
        if (BackupsPanel.Visibility == Visibility.Visible) await LoadBackupsAsync();
    }

    public void FocusDefault() => Tabs.Focus(MainWindow.FocusMode);

    // ---- pickers (unpackaged apps must attach them to the window) --------------------------

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
