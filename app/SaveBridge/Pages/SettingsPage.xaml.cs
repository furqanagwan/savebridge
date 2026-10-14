using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using SaveBridge.Services;

namespace SaveBridge.Pages;

public sealed partial class SettingsPage : Page, IAppPage
{
    static readonly AppSettings Settings = AppSettings.Current;
    bool _ready;

    public SettingsPage()
    {
        InitializeComponent();
        Theme.SelectedIndex = Settings.Theme switch { "Light" => 1, "Dark" => 2, _ => 0 };
        Hints.IsOn = Settings.ControllerHints;
        DataFolder.Text = AppSettings.Folder;
        Converter.Text = Cli.Describe;
        ShowPad();
        Gamepad.Instance.ConnectedChanged += OnPad;
        Unloaded += (_, _) => Gamepad.Instance.ConnectedChanged -= OnPad;
        _ready = true;
    }

    void OnPad(object? sender, EventArgs e) => DispatcherQueue.TryEnqueue(ShowPad);

    void ShowPad() => PadStatus.Text = Gamepad.Instance.Connected
        ? "A controller is connected."
        : "No controller connected. Xbox controllers work directly; others through Steam Input or similar.";

    void Theme_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (!_ready) return;
        Settings.Theme = Theme.SelectedItem as string ?? "System";
        Settings.Save();
        App.Window!.ApplyTheme();
    }

    void Hints_Toggled(object sender, RoutedEventArgs e)
    {
        if (!_ready) return;
        Settings.ControllerHints = Hints.IsOn;
        Settings.Save();
        App.Window!.UpdateHints();
    }

    async void RefreshMeta_Click(object sender, RoutedEventArgs e)
    {
        await Library.Instance.LoadAsync(refresh: true);
        Show("Game info refreshed", Library.Instance.Error ?? "Covers and descriptions are up to date.");
    }

    async void ClearMeta_Click(object sender, RoutedEventArgs e)
    {
        Metadata.ClearCache();
        await Library.Instance.LoadAsync(refresh: true);
        Show("Cache cleared", "Game info was downloaded again.");
    }

    void OpenData_Click(object sender, RoutedEventArgs e) => Ui.OpenFolder(AppSettings.Folder);

    void Show(string title, string message)
    {
        Result.Severity = InfoBarSeverity.Success;
        Result.Title = title;
        Result.Message = message;
        Result.IsOpen = true;
    }

    public void FocusDefault() => Theme.Focus(MainWindow.FocusMode);
}
