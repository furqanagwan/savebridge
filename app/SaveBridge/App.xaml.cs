using Microsoft.UI.Xaml;

namespace SaveBridge;

public partial class App : Application
{
    public static MainWindow? Window { get; private set; }

    public App()
    {
        InitializeComponent();
        FocusVisualKind = FocusVisualKind.HighVisibility; // thick two-tone ring, readable from the couch
    }

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        Window = new MainWindow();
        Window.Activate();
    }
}
