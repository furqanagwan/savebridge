using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using SaveBridge.Models;
using SaveBridge.Services;

namespace SaveBridge.Pages;

public sealed partial class BackupsPage : Page
{
    public BackupsPage()
    {
        InitializeComponent();
        Loaded += async (_, _) => await LoadAsync();
    }

    async Task LoadAsync()
    {
        try
        {
            var list = await Cli.JsonAsync<List<BackupInfo>>("backups");
            List.ItemsSource = list;
            Empty.Visibility = list.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
        }
        catch (Exception e)
        {
            Show(InfoBarSeverity.Error, "Couldn't list backups", e.Message);
        }
    }

    async void Restore_Click(object sender, RoutedEventArgs e)
    {
        var b = (BackupInfo)((Button)sender).Tag;
        var preview = await Cli.RunAsync("restore", b.Game, b.Name, "--dry-run");
        if (!preview.Ok)
        {
            Show(InfoBarSeverity.Error, "Can't restore this backup", preview.Text.Split('\n').Last().Replace("error: ", ""));
            return;
        }
        var dialog = new ContentDialog
        {
            XamlRoot = XamlRoot,
            Title = $"Restore {b.Game} from {b.When}?",
            PrimaryButtonText = "Restore",
            CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Close,
            Content = new ScrollViewer
            {
                MaxHeight = 420,
                Content = new TextBlock
                {
                    Text = preview.Output.Replace("Dry run: nothing written.", "").Trim()
                           + "\n\nThe current saves are backed up first. Make sure the game is closed.",
                    FontFamily = new FontFamily("Consolas"), FontSize = 12,
                    TextWrapping = TextWrapping.Wrap, IsTextSelectionEnabled = true,
                },
            },
        };
        if (await dialog.ShowAsync() != ContentDialogResult.Primary) return;
        var run = await Cli.RunAsync("restore", b.Game, b.Name);
        if (run.Ok) Show(InfoBarSeverity.Success, "Restored", "Start the game online so an Xbox restore uploads to the cloud.");
        else Show(InfoBarSeverity.Error, "Restore failed", run.Text.Split('\n').Last().Replace("error: ", ""));
        await LoadAsync();
    }

    void Show(InfoBarSeverity severity, string title, string message)
    {
        Result.Severity = severity;
        Result.Title = title;
        Result.Message = message;
        Result.IsOpen = true;
    }
}
