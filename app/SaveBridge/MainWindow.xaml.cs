using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;
using SaveBridge.Pages;

namespace SaveBridge;

public sealed partial class MainWindow : Microsoft.UI.Xaml.Window
{
    static readonly Dictionary<string, Type> Pages = new()
    {
        ["games"] = typeof(GamesPage),
        ["backups"] = typeof(BackupsPage),
        ["profile"] = typeof(ProfilePage),
        ["about"] = typeof(AboutPage),
    };

    public MainWindow()
    {
        InitializeComponent();
        ExtendsContentIntoTitleBar = true;
        SetTitleBar(TitleBar);
        var scale = GetDpiForWindow(WinRT.Interop.WindowNative.GetWindowHandle(this)) / 96.0;
        AppWindow.Resize(new Windows.Graphics.SizeInt32((int)(1200 * scale), (int)(820 * scale)));
        AppWindow.SetIcon(Path.Combine(AppContext.BaseDirectory, "Assets", "savebridge.ico"));
        ContentFrame.Navigate(typeof(GamesPage));
        _ = Services.XboxLive.Instance.TrySilentAsync();
    }

    public Frame Frame => ContentFrame;

    [System.Runtime.InteropServices.DllImport("user32.dll")]
    static extern uint GetDpiForWindow(nint hwnd);

    void Nav_SelectionChanged(NavigationView sender, NavigationViewSelectionChangedEventArgs args)
    {
        if (args.SelectedItem is NavigationViewItem { Tag: string tag } && Pages.TryGetValue(tag, out var page)
            && ContentFrame.CurrentSourcePageType != page)
            ContentFrame.Navigate(page);
    }

    void Nav_BackRequested(NavigationView sender, NavigationViewBackRequestedEventArgs args)
    {
        if (ContentFrame.CanGoBack) ContentFrame.GoBack();
    }

    void ContentFrame_Navigated(object sender, NavigationEventArgs e)
    {
        Nav.IsBackEnabled = ContentFrame.CanGoBack;
        var tag = Pages.FirstOrDefault(p => p.Value == e.SourcePageType).Key ?? "games";
        foreach (var item in Nav.MenuItems.Concat(Nav.FooterMenuItems).OfType<NavigationViewItem>())
            if ((string)item.Tag == tag && !item.IsSelected) item.IsSelected = true;
    }
}
