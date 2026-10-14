using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Animation;
using Microsoft.UI.Xaml.Media.Imaging;
using Microsoft.UI.Xaml.Navigation;
using SaveBridge.Models;
using SaveBridge.Pages;
using SaveBridge.Services;
using Windows.System;

namespace SaveBridge;

public sealed partial class MainWindow : Window
{
    static readonly (string Tag, Type Page)[] Sections =
    [
        ("library", typeof(LibraryPage)),
        ("backups", typeof(BackupsPage)),
        ("profile", typeof(ProfilePage)),
        ("settings", typeof(SettingsPage)),
        ("about", typeof(AboutPage)),
    ];

    public MainWindow()
    {
        InitializeComponent();
        ExtendsContentIntoTitleBar = true;
        SetTitleBar(AppTitleBar);
        var scale = GetDpiForWindow(WinRT.Interop.WindowNative.GetWindowHandle(this)) / 96.0;
        AppWindow.Resize(new Windows.Graphics.SizeInt32((int)(1360 * scale), (int)(880 * scale)));
        AppWindow.SetIcon(Path.Combine(AppContext.BaseDirectory, "Assets", "savebridge.ico"));
        ApplyTheme();
        // App-wide controller buttons run even when a control already handled the key
        // (some controls swallow GamepadB); see Root_KeyDown.
        Root.AddHandler(UIElement.KeyDownEvent, new KeyEventHandler(Root_KeyDown), handledEventsToo: true);

        Gamepad.Instance.ConnectedChanged += (_, _) => DispatcherQueue.TryEnqueue(UpdateHints);
        Gamepad.Instance.Scroll += (_, dy) => ScrollPage(dy);
        Gamepad.Instance.Button += (_, b) => OnPadButton(b);
        Gamepad.Instance.Start(this);
        XboxLive.Instance.Changed += (_, _) => DispatcherQueue.TryEnqueue(UpdateAvatar);
        Library.Instance.Changed += (_, _) => DispatcherQueue.TryEnqueue(() =>
        {
            LibraryCount.Value = Library.Instance.Games.Count;
            LibraryCount.Visibility = Library.Instance.Games.Count > 0 ? Visibility.Visible : Visibility.Collapsed;
        });

        ContentFrame.Navigate(typeof(LibraryPage));
        _ = Library.Instance.LoadAsync();
        if (Environment.GetEnvironmentVariable("SAVEBRIDGE_DEBUG_FOCUS") == "1") ShowFocusInTitle();
        _ = XboxLive.Instance.TrySilentAsync();
    }

    public Frame Frame => ContentFrame;

    public void ApplyTheme() => Root.RequestedTheme = AppSettings.Current.ElementTheme;

    public void UpdateHints() =>
        HintBar.Visibility = Gamepad.Instance.Connected && AppSettings.Current.ControllerHints
            ? Visibility.Visible : Visibility.Collapsed;

    void UpdateAvatar()
    {
        var p = XboxLive.Instance.Profile;
        Avatar.DisplayName = p?.Gamertag ?? "";
        Avatar.ProfilePicture = p != null && Uri.TryCreate(p.PictureUrl, UriKind.Absolute, out var u) ? new BitmapImage(u) : null;
        ToolTipService.SetToolTip(ProfileButton, p is null ? "Sign in to Xbox" : p.Gamertag);
    }

    // ---- navigation -----------------------------------------------------------------

    public void Navigate(Type page, object? parameter = null)
    {
        if (ContentFrame.CurrentSourcePageType == page && parameter is null) return;
        ContentFrame.Navigate(page, parameter, new SlideNavigationTransitionInfo
        { Effect = SlideNavigationTransitionEffect.FromRight });
    }

    void Nav_SelectionChanged(NavigationView sender, NavigationViewSelectionChangedEventArgs args)
    {
        var tag = args.IsSettingsSelected ? "settings" : (args.SelectedItem as NavigationViewItem)?.Tag as string;
        var section = Sections.FirstOrDefault(s => s.Tag == tag);
        if (section.Page != null && ContentFrame.CurrentSourcePageType != section.Page)
            ContentFrame.Navigate(section.Page, null, new EntranceNavigationTransitionInfo());
    }

    void TitleBar_BackRequested(TitleBar sender, object args) => GoBack();

    void TitleBar_PaneToggleRequested(TitleBar sender, object args) => Nav.IsPaneOpen = !Nav.IsPaneOpen;

    bool GoBack()
    {
        if (!ContentFrame.CanGoBack) return false;
        ContentFrame.GoBack();
        return true;
    }

    void ContentFrame_Navigated(object sender, NavigationEventArgs e)
    {
        AppTitleBar.IsBackButtonEnabled = ContentFrame.CanGoBack;
        var page = e.SourcePageType == typeof(GamePage) ? typeof(LibraryPage) : e.SourcePageType;
        var tag = Sections.FirstOrDefault(s => s.Page == page).Tag;
        if (tag == "settings") Nav.SelectedItem = Nav.SettingsItem;
        else
            foreach (var item in Nav.MenuItems.Concat(Nav.FooterMenuItems).OfType<NavigationViewItem>())
                if ((string)item.Tag == tag && !item.IsSelected) item.IsSelected = true;

        // Start the D-pad on the page's content, not on the window chrome.
        if (e.Content is FrameworkElement { } content and IAppPage appPage)
        {
            if (content.IsLoaded) appPage.FocusDefault();
            else content.Loaded += FocusOnce;
            void FocusOnce(object s, RoutedEventArgs a)
            {
                content.Loaded -= FocusOnce;
                appPage.FocusDefault();
            }
        }
    }

    /// <summary>How pages should give focus: visibly for controller/keyboard users, quietly for mouse users.</summary>
    public static FocusState FocusMode => Gamepad.Instance.LastInputWasGamepad ? FocusState.Keyboard : FocusState.Programmatic;

    // ---- controller and keyboard shortcuts ----------------------------------------------

    string _lastKey = "";
    Microsoft.UI.Dispatching.DispatcherQueueTimer? _focusTimer;

    void OnPadButton(PadButton button)
    {
        var root = Root.XamlRoot;
        switch (button)
        {
            case PadButton.B:
                // Like a console: close what's open, leave a text field, otherwise go back.
                if (root != null && VisualTreeHelper.GetOpenPopupsForXamlRoot(root).Count > 0)
                    Gamepad.Instance.Press(0x1B);  // Escape closes dialogs, flyouts and drop-downs
                else if (root != null && FocusManager.GetFocusedElement(root) is TextBox or AutoSuggestBox or PasswordBox)
                    { if (ContentFrame.Content is IAppPage p) p.FocusDefault(); }
                else GoBack();
                break;
            case PadButton.LeftShoulder: SwitchSection(-1); break;
            case PadButton.RightShoulder: SwitchSection(+1); break;
            case PadButton.Y:
                if (ContentFrame.Content is IAppPage page) _ = page.RefreshAsync();
                break;
            case PadButton.View: Search.Focus(FocusState.Keyboard); break;
            case PadButton.Menu: Navigate(typeof(SettingsPage)); break;
        }
    }

    void Root_KeyDown(object sender, KeyRoutedEventArgs e)
    {
        _lastKey = $"{e.Key} handled={e.Handled}";
        if (_focusTimer != null && e.Key is VirtualKey.F6 or VirtualKey.F7 or VirtualKey.F8)
        {
            // Development aid (SAVEBRIDGE_DEBUG_FOCUS=1): F6/F7/F8 act as B/LB/RB.
            OnPadButton(e.Key == VirtualKey.F6 ? PadButton.B : e.Key == VirtualKey.F7 ? PadButton.LeftShoulder : PadButton.RightShoulder);
            e.Handled = true;
            return;
        }
        switch (e.Key)
        {
            case VirtualKey.GoBack:
                e.Handled = GoBack();
                break;
            case VirtualKey.F5:
                if (ContentFrame.Content is IAppPage page) _ = page.RefreshAsync();
                e.Handled = true;
                break;
        }
    }

    /// <summary>
    /// A controller press with focus on nothing useful (none, a scroll area, the frame) would
    /// be lost; instead it puts focus on the page's main control, like a console app does.
    /// </summary>
    void Root_PreviewKeyDown(object sender, KeyRoutedEventArgs e)
    {
        // The controller's D-pad and A arrive as gamepad or arrow/Enter keys depending on the path.
        if (e.Key is not (VirtualKey.GamepadA or VirtualKey.GamepadDPadUp or VirtualKey.GamepadDPadDown
                          or VirtualKey.GamepadDPadLeft or VirtualKey.GamepadDPadRight or VirtualKey.Up
                          or VirtualKey.Down or VirtualKey.Left or VirtualKey.Right or VirtualKey.Enter)) return;
        var focused = Root.XamlRoot is { } root ? FocusManager.GetFocusedElement(root) : null;
        if (focused is Control { FocusState: not FocusState.Keyboard } shown and not ScrollViewer)
        {
            // Focus set by mouse or code has no visible ring: the first press shows where you are.
            Gamepad.Instance.LastInputWasGamepad = true;
            e.Handled = shown.Focus(FocusState.Keyboard);
            return;
        }
        if (focused is not (null or ScrollViewer or Microsoft.UI.Xaml.Controls.Frame or Microsoft.UI.Xaml.Controls.Page or NavigationView)) return;
        if (ContentFrame.Content is IAppPage page)
        {
            Gamepad.Instance.LastInputWasGamepad = true;
            page.FocusDefault();
            e.Handled = true;
        }
    }

    void Root_PointerPressed(object sender, PointerRoutedEventArgs e) => Gamepad.Instance.LastInputWasGamepad = false;

    void SwitchSection(int step)
    {
        var current = ContentFrame.CurrentSourcePageType == typeof(GamePage) ? typeof(LibraryPage)
                                                                             : ContentFrame.CurrentSourcePageType;
        var i = Array.FindIndex(Sections, s => s.Page == current);
        var next = Sections[((i < 0 ? 0 : i) + step + Sections.Length) % Sections.Length];
        ContentFrame.Navigate(next.Page, null, new SlideNavigationTransitionInfo
        { Effect = step > 0 ? SlideNavigationTransitionEffect.FromRight : SlideNavigationTransitionEffect.FromLeft });
    }

    void ScrollPage(double dy)
    {
        DependencyObject? node = FocusManager.GetFocusedElement(Root.XamlRoot) as DependencyObject;
        while (node != null && node is not ScrollViewer) node = VisualTreeHelper.GetParent(node);
        var viewer = node as ScrollViewer ?? FindScrollViewer(ContentFrame.Content as DependencyObject);
        viewer?.ChangeView(null, viewer.VerticalOffset + dy, null, true);
    }

    static ScrollViewer? FindScrollViewer(DependencyObject? root)
    {
        if (root is null) return null;
        if (root is ScrollViewer sv && sv.ScrollableHeight > 0) return sv;
        for (var i = 0; i < VisualTreeHelper.GetChildrenCount(root); i++)
            if (FindScrollViewer(VisualTreeHelper.GetChild(root, i)) is { } found) return found;
        return null;
    }

    // ---- title bar --------------------------------------------------------------------

    void Search_TextChanged(AutoSuggestBox sender, AutoSuggestBoxTextChangedEventArgs args)
    {
        if (args.Reason != AutoSuggestionBoxTextChangeReason.UserInput) return;
        var q = sender.Text.Trim();
        sender.ItemsSource = q.Length == 0 ? null : Library.Instance.Games
            .Where(g => g.Name.Contains(q, StringComparison.OrdinalIgnoreCase)).Take(8).ToList();
        if (ContentFrame.Content is LibraryPage library) library.SetFilter(q);
    }

    void Search_SuggestionChosen(AutoSuggestBox sender, AutoSuggestBoxSuggestionChosenEventArgs args)
    {
        if (args.SelectedItem is LibraryGame game) sender.Text = game.Name;
    }

    void Search_QuerySubmitted(AutoSuggestBox sender, AutoSuggestBoxQuerySubmittedEventArgs args)
    {
        if (args.ChosenSuggestion is LibraryGame game)
        {
            Navigate(typeof(GamePage), game.Id);
            sender.Text = "";
            return;
        }
        Navigate(typeof(LibraryPage));
        if (ContentFrame.Content is LibraryPage library) library.SetFilter(args.QueryText.Trim());
    }

    void ProfileButton_Click(object sender, RoutedEventArgs e) => Navigate(typeof(ProfilePage));

    /// <summary>Development aid: the focused element and its focus state, in the title bar.</summary>
    void ShowFocusInTitle()
    {
        var timer = _focusTimer = DispatcherQueue.CreateTimer();  // kept in a field so it isn't collected
        timer.Interval = TimeSpan.FromMilliseconds(250);
        timer.Tick += (_, _) =>
        {
            var f = Root.XamlRoot is { } root ? FocusManager.GetFocusedElement(root) : null;
            AppTitleBar.Subtitle = f switch
            {
                null => "focus: none",
                Control c => $"focus: {c.GetType().Name} {c.Name} ({c.FocusState})",
                _ => $"focus: {f.GetType().Name}",
            } + $"  key: {_lastKey}";
        };
        timer.Start();
    }

    [System.Runtime.InteropServices.DllImport("user32.dll")]
    static extern uint GetDpiForWindow(nint hwnd);
}
