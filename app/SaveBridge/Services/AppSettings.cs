using System.Text.Json;
using Microsoft.UI.Xaml;

namespace SaveBridge.Services;

/// <summary>The app's own preferences, in %LOCALAPPDATA%\savebridge\app-settings.json.</summary>
public sealed class AppSettings
{
    public static string Folder => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "savebridge");
    static string FilePath => Path.Combine(Folder, "app-settings.json");

    public static AppSettings Current { get; } = Load();

    public string Theme { get; set; } = "System";        // System, Light, Dark
    public bool ControllerHints { get; set; } = true;

    public ElementTheme ElementTheme => Theme switch
    {
        "Light" => ElementTheme.Light,
        "Dark" => ElementTheme.Dark,
        _ => ElementTheme.Default,
    };

    static AppSettings Load()
    {
        try { return JsonSerializer.Deserialize<AppSettings>(File.ReadAllText(FilePath)) ?? new(); }
        catch (Exception) { return new(); }
    }

    public void Save()
    {
        try
        {
            Directory.CreateDirectory(Folder);
            File.WriteAllText(FilePath, JsonSerializer.Serialize(this));
        }
        catch (IOException) { }
    }
}
