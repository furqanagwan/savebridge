using System.Diagnostics;
using Microsoft.UI.Xaml;

namespace SaveBridge.Services;

/// <summary>Small helpers for x:Bind and shell actions.</summary>
public static class Ui
{
    public static Visibility Show(bool value) => value ? Visibility.Visible : Visibility.Collapsed;
    public static Visibility Hide(bool value) => value ? Visibility.Collapsed : Visibility.Visible;
    public static Visibility ShowText(string? value) => string.IsNullOrWhiteSpace(value) ? Visibility.Collapsed : Visibility.Visible;
    public static double Dim(bool active) => active ? 1.0 : 0.45;

    /// <summary>Opens a folder in Explorer, or the nearest parent that exists.</summary>
    public static void OpenFolder(string? path)
    {
        if (string.IsNullOrEmpty(path)) return;
        var dir = new DirectoryInfo(path);
        while (dir != null && !dir.Exists) dir = dir.Parent;
        if (dir != null) Process.Start(new ProcessStartInfo("explorer.exe", $"\"{dir.FullName}\"") { UseShellExecute = true });
    }

    public static void CopyText(string text)
    {
        var package = new Windows.ApplicationModel.DataTransfer.DataPackage();
        package.SetText(text);
        Windows.ApplicationModel.DataTransfer.Clipboard.SetContent(package);
    }

    public static void OpenUrl(string url) => Process.Start(new ProcessStartInfo(url) { UseShellExecute = true });
}
