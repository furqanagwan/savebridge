using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using SaveBridge.Models;
using SaveBridge.Services;

namespace SaveBridge.Pages;

public sealed record BackupRow(BackupInfo Backup, string Title, string Detail, Uri? Art);

public sealed partial class BackupsPage : Page, IAppPage
{
    bool _focusPending;

    public BackupsPage()
    {
        InitializeComponent();
        Loaded += async (_, _) => await RefreshAsync();
        // The list loads after the page appears: focus its first row once that row exists.
        List.ContainerContentChanging += (_, args) =>
        {
            if (_focusPending && args.ItemIndex == 0 && !args.InRecycleQueue)
                DispatcherQueue.TryEnqueue(Microsoft.UI.Dispatching.DispatcherQueuePriority.Low, FocusDefault);
        };
    }

    public async Task RefreshAsync()
    {
        try
        {
            await Library.Instance.LoadAsync();
            var list = await Cli.JsonAsync<List<BackupInfo>>("backups");
            List.ItemsSource = list.Select(b =>
            {
                var game = Library.Instance.Find(b.Game);
                return new BackupRow(b, game?.Name ?? b.Game, $"{b.Where} saves · {b.When} · {b.SizeText}",
                                     game?.Meta?.Header is { } h ? new Uri(h) : null);
            }).ToList();
            Empty.Visibility = Ui.Show(list.Count == 0);
        }
        catch (Exception e) { Show(InfoBarSeverity.Error, "Couldn't list backups", e.Message); }
    }

    async void Restore_Click(object sender, RoutedEventArgs e) => await RestoreAsync((BackupInfo)((Button)sender).Tag);

    // A on a controller (or a click) on the row restores it too.
    async void List_ItemClick(object sender, ItemClickEventArgs e) => await RestoreAsync(((BackupRow)e.ClickedItem).Backup);

    async Task RestoreAsync(BackupInfo b)
    {
        var name = Library.Instance.Find(b.Game)?.Name ?? b.Game;
        var r = await Writes.PreviewAndRunAsync(XamlRoot, ["restore", b.Game, b.Name],
                                                $"Restore {name} ({b.Where}) from {b.When}?", "Restore");
        switch (r.Outcome)
        {
            case WriteOutcome.Done:
                Show(InfoBarSeverity.Success, "Restored", r.Summary + " Start the game online so an Xbox restore uploads.");
                await Library.Instance.RefreshLocationAsync(b.Game);
                break;
            case WriteOutcome.Refused: Show(InfoBarSeverity.Error, "Can't restore this backup", r.Summary); break;
            case WriteOutcome.Failed: Show(InfoBarSeverity.Error, "Restore failed", r.Summary); break;
        }
        await RefreshAsync();
    }

    void OpenFolder_Click(object sender, RoutedEventArgs e) => Ui.OpenFolder(Path.Combine(AppSettings.Folder, "backups"));

    void Show(InfoBarSeverity severity, string title, string message)
    {
        Result.Severity = severity;
        Result.Title = title;
        Result.Message = message;
        Result.IsOpen = true;
    }

    public void FocusDefault() =>
        _focusPending = List.ContainerFromIndex(0) is not ListViewItem first || !first.Focus(MainWindow.FocusMode);
}
