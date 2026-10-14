using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml.Controls;
using SaveBridge.Models;
using SaveBridge.Services;

namespace SaveBridge.Pages;

public sealed record CommunityRow(CommunitySave Save, Uri? Art);

public sealed partial class CommunityPage : Page, IAppPage
{
    List<CommunitySave> _all = [];
    bool _focusPending;

    public CommunityPage()
    {
        InitializeComponent();
        Loaded += async (_, _) => await RefreshAsync();
        List.ContainerContentChanging += (_, args) =>
        {
            if (_focusPending && args.ItemIndex == 0 && !args.InRecycleQueue)
                DispatcherQueue.TryEnqueue(DispatcherQueuePriority.Low, FocusDefault);
        };
    }

    public async Task RefreshAsync()
    {
        Busy.IsActive = true;
        Error.IsOpen = false;
        try
        {
            await Library.Instance.LoadAsync();
            _all = await Cli.JsonAsync<List<CommunitySave>>("community", "list");
            Show();
        }
        catch (Exception e)
        {
            Error.Title = "Couldn't load community saves";
            Error.Message = e.Message;
            Error.IsOpen = true;
        }
        finally { Busy.IsActive = false; }
    }

    void Show()
    {
        var platform = Platforms.SelectedItem?.Tag as string ?? "all";
        var rows = _all.Where(s => platform == "all" || s.Platform == platform)
            .Select(s => new CommunityRow(s, Library.Instance.Find(s.Game)?.Meta?.Header is { } h ? new Uri(h) : null))
            .ToList();
        List.ItemsSource = rows;
        Empty.Text = _all.Count == 0 ? "No community saves yet. Share one with \"Share a save\"."
                                     : "No saves from this platform yet.";
        Empty.Visibility = Ui.Show(rows.Count == 0 && !Busy.IsActive);
    }

    void Platforms_SelectionChanged(SelectorBar sender, SelectorBarSelectionChangedEventArgs args) => Show();

    void List_ItemClick(object sender, ItemClickEventArgs e) =>
        App.Window!.Navigate(typeof(GamePage), ((CommunityRow)e.ClickedItem).Save.Game + "#community");

    public void FocusDefault() =>
        _focusPending = List.ContainerFromIndex(0) is not ListViewItem first || !first.Focus(MainWindow.FocusMode);
}
