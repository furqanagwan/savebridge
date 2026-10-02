using Microsoft.UI.Xaml.Controls;

namespace SaveBridge.Pages;

public sealed partial class AboutPage : Page
{
    public AboutPage()
    {
        InitializeComponent();
        var version = typeof(AboutPage).Assembly.GetName().Version;
        Engine.Text = $"Version {version?.ToString(3)} · converter: {Services.Cli.Describe}";
    }
}
