using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;

namespace SaveBridge.Services;

public enum WriteOutcome { Done, Cancelled, Refused, Failed }

public sealed record WriteResult(WriteOutcome Outcome, string Summary, string Log);

/// <summary>
/// Every change goes the same way: a dry run, a dialog showing exactly what will
/// change, then the real run (which backs up first and verifies after).
/// </summary>
public static class Writes
{
    public static async Task<WriteResult> PreviewAndRunAsync(XamlRoot root, IReadOnlyList<string> args,
                                                             string title, string confirm = "Write")
    {
        var preview = await Cli.RunAsync([.. args, "--dry-run"]);
        if (!preview.Ok) return new(WriteOutcome.Refused, LastLine(preview), preview.Text);

        var dialog = new ContentDialog
        {
            XamlRoot = root,
            Title = title,
            PrimaryButtonText = confirm,
            CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Close,
            Content = new ScrollViewer
            {
                MaxHeight = 440,
                Content = new StackPanel
                {
                    Spacing = 12,
                    Children =
                    {
                        new TextBlock
                        {
                            Text = preview.Output.Replace("Dry run: nothing written.", "").Trim(),
                            FontFamily = new FontFamily("Cascadia Mono, Consolas"), FontSize = 12,
                            IsTextSelectionEnabled = true, TextWrapping = TextWrapping.Wrap,
                        },
                        new InfoBar
                        {
                            IsOpen = true, IsClosable = false, Severity = InfoBarSeverity.Informational,
                            Message = "The current saves are backed up first. Close the game before continuing.",
                        },
                    },
                },
            },
        };
        if (await dialog.ShowAsync() != ContentDialogResult.Primary)
            return new(WriteOutcome.Cancelled, "", preview.Text);

        var run = await Cli.RunAsync(args);
        if (!run.Ok) return new(WriteOutcome.Failed, LastLine(run), run.Text);
        var summary = string.Join(" ", run.Output.Split('\n').Select(l => l.Trim()).Where(l =>
            l.StartsWith("Wrote") || l.StartsWith("Open the game") || l.StartsWith("If Steam") ||
            l.StartsWith("This game's") || l.StartsWith("Not in the backup")));
        return new(WriteOutcome.Done, summary, run.Text);
    }

    public static string LastLine(CliResult r) =>
        (r.Error.Length > 0 ? r.Error : r.Output).Split('\n').LastOrDefault(l => l.Trim().Length > 0)?
        .Replace("error: ", "").Trim() ?? "Unknown error";
}
